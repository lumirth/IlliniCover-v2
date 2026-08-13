import hashlib
import hmac
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, connection

from identity.models import (
    Account,
    ActorAccountLink,
    ActorAccountLinkReceipt,
    IdentityRateBucket,
    InstallationActor,
    InstallationOperationReceipt,
)
from identity.rate_limits import _network_key
from identity.services import (
    IdentityIdempotencyConflict,
    create_installation,
    link_installation,
)


def _probe_request_id(label: str) -> uuid.UUID:
    value = bytearray(
        hmac.new(
            settings.SECRET_KEY.encode(),
            f"identity-concurrency-probe:{label}".encode(),
            hashlib.sha256,
        ).digest()[:16]
    )
    value[6] = (value[6] & 0x0F) | 0x40
    value[8] = (value[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(value))


EQUAL_REQUEST_ID = _probe_request_id("equal")
LIMITED_REQUEST_IDS = (
    _probe_request_id("limited-a"),
    _probe_request_id("limited-b"),
)
LINK_INSTALLATION_REQUEST_IDS = tuple(
    _probe_request_id(f"link-installation-{label}") for label in ("a", "b", "c", "d")
)
LINK_REQUEST_IDS = tuple(
    _probe_request_id(f"link-request-{label}") for label in ("a", "b", "c", "d", "e")
)
PROBE_INSTALLATION_REQUEST_IDS = (
    EQUAL_REQUEST_ID,
    *LIMITED_REQUEST_IDS,
    *LINK_INSTALLATION_REQUEST_IDS,
)
LINK_ACCOUNT_ID = _probe_request_id("link-account")
EQUAL_ADDRESS = "192.0.2.220"
LIMITED_ADDRESS = "192.0.2.221"
LINK_ADDRESS = "192.0.2.222"


class Command(BaseCommand):
    help = "Run bounded PostgreSQL identity idempotency and rate-limit probes."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("The identity concurrency probe requires PostgreSQL")
        if getattr(settings, "DATABASE_CONNECTION_MODE", "direct") != "direct":
            raise CommandError("The identity concurrency probe requires DATABASE_MODE=direct")

        self._cleanup()
        baseline = self._counts()
        original_limit = settings.INSTALLATION_ISSUANCE_RATE_LIMIT
        try:
            settings.INSTALLATION_ISSUANCE_RATE_LIMIT = (8, 3600)
            equal_result = self._equal_request_probe()
            link_result = self._link_receipt_probe()
            settings.INSTALLATION_ISSUANCE_RATE_LIMIT = (1, 3600)
            limited_result = self._network_limit_probe()
        finally:
            settings.INSTALLATION_ISSUANCE_RATE_LIMIT = original_limit
            self._cleanup()
        if self._counts() != baseline:
            raise CommandError("identity probe did not restore its exact durable row counts")
        self.stdout.write(
            self.style.SUCCESS(
                "PostgreSQL identity concurrency probes passed: "
                f"equal={equal_result}, link={link_result}, "
                f"limited={limited_result}, durableRows=0"
            )
        )

    @staticmethod
    def _counts() -> tuple[int, int, int, int, int, int]:
        return (
            Account.objects.count(),
            InstallationActor.objects.count(),
            InstallationOperationReceipt.objects.count(),
            ActorAccountLink.objects.count(),
            ActorAccountLinkReceipt.objects.count(),
            IdentityRateBucket.objects.count(),
        )

    @staticmethod
    def _cleanup() -> None:
        actor_ids = InstallationOperationReceipt.objects.filter(
            request_id__in=PROBE_INSTALLATION_REQUEST_IDS
        ).values_list("actor_id", flat=True)
        InstallationActor.objects.filter(pk__in=actor_ids).delete()
        ActorAccountLinkReceipt.objects.filter(request_id__in=LINK_REQUEST_IDS).delete()
        ActorAccountLink.objects.filter(account_id=LINK_ACCOUNT_ID).delete()
        Account.objects.filter(pk=LINK_ACCOUNT_ID).delete()
        for address in (EQUAL_ADDRESS, LIMITED_ADDRESS, LINK_ADDRESS):
            IdentityRateBucket.objects.filter(
                key__startswith=f"identity-rate:{_network_key(address)}:"
            ).delete()

    @staticmethod
    def _worker(barrier, *, request_id, token, address):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                receipt = create_installation(
                    request_id=request_id,
                    raw_token=token,
                    remote_address=address,
                )
                return "created", str(receipt.actor_id)
            except Exception as error:  # report only class; never token or database text
                return type(error).__name__, ""
        finally:
            close_old_connections()

    def _equal_request_probe(self) -> str:
        barrier = Barrier(2)
        token = "ic_install_" + secrets.token_urlsafe(32)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    self._worker,
                    barrier,
                    request_id=EQUAL_REQUEST_ID,
                    token=token,
                    address=EQUAL_ADDRESS,
                )
                for _ in range(2)
            ]
            results = [future.result() for future in futures]
        if results[0][0] != "created" or results[1][0] != "created":
            raise CommandError(f"equal request probe failed by class: {results!r}")
        if results[0][1] != results[1][1]:
            raise CommandError("equal request probe returned different actors")
        if InstallationOperationReceipt.objects.filter(pk=EQUAL_REQUEST_ID).count() != 1:
            raise CommandError("equal request probe did not persist exactly one receipt")
        return "one-actor"

    @staticmethod
    def _link_worker(barrier, *, request_id, token):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                account = Account.objects.get(pk=LINK_ACCOUNT_ID)
                link = link_installation(account, request_id, token)
                if link is None:
                    return "invalid", ""
                return "linked", str(link.actor_id)
            except Exception as error:  # report only class; never token or database text
                return type(error).__name__, ""
        finally:
            close_old_connections()

    @staticmethod
    def _create_link_probe_installation(index: int, token: str):
        return create_installation(
            request_id=LINK_INSTALLATION_REQUEST_IDS[index],
            raw_token=token,
            remote_address=LINK_ADDRESS,
        ).actor

    def _link_receipt_probe(self) -> str:
        account = Account.objects.create_user(
            f"identity-probe-{LINK_ACCOUNT_ID.hex}@example.invalid",
            id=LINK_ACCOUNT_ID,
        )
        tokens = ["ic_install_" + secrets.token_urlsafe(32) for _ in range(4)]
        actors = [
            self._create_link_probe_installation(index, token) for index, token in enumerate(tokens)
        ]

        initial = link_installation(account, LINK_REQUEST_IDS[0], tokens[0])
        fresh = link_installation(account, LINK_REQUEST_IDS[1], tokens[0])
        if initial is None or fresh is None or initial.pk != fresh.pk:
            raise CommandError("sequential link retry did not return the original link")
        if (
            ActorAccountLinkReceipt.objects.filter(
                request_id__in=LINK_REQUEST_IDS[:2],
                link=initial,
            ).count()
            != 2
        ):
            raise CommandError("sequential link retry did not reserve both request UUIDs")
        try:
            link_installation(account, LINK_REQUEST_IDS[1], tokens[1])
        except IdentityIdempotencyConflict:
            pass
        else:
            raise CommandError("accepted link UUID was redirected to another actor")
        if ActorAccountLink.objects.filter(actor=actors[1]).exists():
            raise CommandError("conflicting link UUID unexpectedly linked another actor")

        same_actor_barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            same_actor_futures = [
                pool.submit(
                    self._link_worker,
                    same_actor_barrier,
                    request_id=request_id,
                    token=tokens[2],
                )
                for request_id in LINK_REQUEST_IDS[2:4]
            ]
            same_actor_results = [future.result() for future in same_actor_futures]
        if [result[0] for result in same_actor_results] != ["linked", "linked"]:
            raise CommandError(
                f"same-actor fresh UUID probe failed by class: {same_actor_results!r}"
            )
        if len({result[1] for result in same_actor_results}) != 1:
            raise CommandError("same-actor fresh UUID probe returned different actors")
        if (
            ActorAccountLinkReceipt.objects.filter(
                request_id__in=LINK_REQUEST_IDS[2:4],
                link__actor=actors[2],
            ).count()
            != 2
        ):
            raise CommandError("same-actor fresh UUID probe did not persist two receipts")

        competing_barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            competing_futures = [
                pool.submit(
                    self._link_worker,
                    competing_barrier,
                    request_id=LINK_REQUEST_IDS[4],
                    token=token,
                )
                for token in (tokens[1], tokens[3])
            ]
            competing_results = [future.result() for future in competing_futures]
        if sorted(result[0] for result in competing_results) != [
            "IdentityIdempotencyConflict",
            "linked",
        ]:
            raise CommandError(f"competing link UUID probe failed by class: {competing_results!r}")
        if ActorAccountLinkReceipt.objects.filter(pk=LINK_REQUEST_IDS[4]).count() != 1:
            raise CommandError("competing link UUID probe did not persist exactly one receipt")
        return "sequential-reserved-concurrent-safe"

    def _network_limit_probe(self) -> str:
        barrier = Barrier(2)
        payloads = [
            (request_id, "ic_install_" + secrets.token_urlsafe(32))
            for request_id in LIMITED_REQUEST_IDS
        ]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    self._worker,
                    barrier,
                    request_id=request_id,
                    token=token,
                    address=LIMITED_ADDRESS,
                )
                for request_id, token in payloads
            ]
            results = [future.result() for future in futures]
        if sorted(result[0] for result in results) != [
            "InstallationIssuanceRateLimited",
            "created",
        ]:
            raise CommandError(f"network limit probe failed by class: {results!r}")
        return "one-created-one-limited"
