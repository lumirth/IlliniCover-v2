from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import URLValidator
from django.db import transaction
from django.utils.dateparse import parse_datetime
from operations.jobs import JobAlreadyRunning, managed_job
from venues.models import Venue

from context.models import AdvertisedAdmission, SourceFetch


@dataclass(frozen=True, slots=True)
class AdmissionRow:
    venue: Venue
    price_cents: int
    starts_at: datetime
    ends_at: datetime | None
    qualification: str
    is_unconditional: bool


def _aware_datetime(value: object, field: str, *, required: bool = True) -> datetime | None:
    if value is None and not required:
        return None
    parsed = parse_datetime(value) if isinstance(value, str) else None
    if parsed is None or parsed.tzinfo is None:
        raise CommandError(f"{field} must be an ISO 8601 timestamp with an explicit timezone")
    return parsed


class Command(BaseCommand):
    help = "Import a reviewed, provenance-bearing advertised-admission JSON document."

    def add_arguments(self, parser):
        parser.add_argument("input")
        parser.add_argument("--source-identifier", required=True)
        parser.add_argument("--source-url", required=True)
        parser.add_argument("--fetched-at", required=True)
        parser.add_argument("--external-key", required=True)
        parser.add_argument("--parser-version", default="advertised_admission_json_v1")

    def handle(self, *args, **options):
        source_path = Path(options["input"]).resolve()
        if not source_path.is_file():
            raise CommandError("input must be an existing regular JSON file")
        try:
            payload_bytes = source_path.read_bytes()
            payload = json.loads(payload_bytes)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CommandError("input must be readable UTF-8 JSON") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("admissions"), list):
            raise CommandError("input must be an object containing an admissions array")
        try:
            URLValidator(schemes=("https",))(options["source_url"])
        except ValidationError as error:
            raise CommandError("source-url must be an HTTPS URL") from error
        fetched_at = _aware_datetime(options["fetched_at"], "fetched-at")
        assert fetched_at is not None
        rows = self._validated_rows(payload["admissions"])
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()

        try:
            with managed_job("import_advertised_admissions") as run:
                with transaction.atomic():
                    source, source_created = SourceFetch.objects.get_or_create(
                        source_identifier=options["source_identifier"],
                        external_key=options["external_key"],
                        payload_hash=payload_hash,
                        defaults={
                            "fetched_at": fetched_at,
                            "source_url": options["source_url"],
                            "parser_version": options["parser_version"],
                            "status": "succeeded",
                        },
                    )
                    if not source_created and (
                        source.fetched_at != fetched_at
                        or source.source_url != options["source_url"]
                        or source.parser_version != options["parser_version"]
                        or source.status != "succeeded"
                    ):
                        raise CommandError(
                            "the same source identifier/key/hash already has different provenance"
                        )
                    created = 0
                    for row in rows:
                        _, was_created = AdvertisedAdmission.objects.get_or_create(
                            venue=row.venue,
                            price_cents=row.price_cents,
                            starts_at=row.starts_at,
                            ends_at=row.ends_at,
                            qualification=row.qualification,
                            is_unconditional=row.is_unconditional,
                            source_fetch=source,
                        )
                        created += int(was_created)
                run.result_summary = {
                    "sourceFetchId": str(source.pk),
                    "payloadSha256": payload_hash,
                    "rowsSeen": len(rows),
                    "rowsCreated": created,
                }
        except JobAlreadyRunning:
            self.stdout.write("advertised-admission import is already running")
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"advertised admissions: {len(rows)} rows checked, {created} facts created"
            )
        )

    def _validated_rows(self, values: list[object]) -> tuple[AdmissionRow, ...]:
        rows: list[AdmissionRow] = []
        for index, value in enumerate(values):
            prefix = f"admissions[{index}]"
            if not isinstance(value, dict):
                raise CommandError(f"{prefix} must be an object")
            try:
                venue = Venue.objects.get(slug=value.get("venueSlug"), is_active=True)
            except Venue.DoesNotExist as error:
                raise CommandError(f"{prefix}.venueSlug is not an active venue") from error
            price = value.get("priceCents")
            if isinstance(price, bool) or not isinstance(price, int) or not 0 <= price <= 7_000:
                raise CommandError(f"{prefix}.priceCents must be an integer from 0 through 7000")
            starts_at = _aware_datetime(value.get("startsAt"), f"{prefix}.startsAt")
            assert starts_at is not None
            ends_at = _aware_datetime(
                value.get("endsAt"), f"{prefix}.endsAt", required=False
            )
            if ends_at is not None and ends_at <= starts_at:
                raise CommandError(f"{prefix}.endsAt must be later than startsAt")
            qualification = value.get("qualification", "")
            if not isinstance(qualification, str) or len(qualification) > 240:
                raise CommandError(f"{prefix}.qualification must be at most 240 characters")
            qualification = qualification.strip()
            is_unconditional = value.get("isUnconditional")
            if not isinstance(is_unconditional, bool):
                raise CommandError(f"{prefix}.isUnconditional must be a boolean")
            if is_unconditional and qualification:
                raise CommandError(
                    f"{prefix} cannot be unconditional while carrying a qualification"
                )
            rows.append(
                AdmissionRow(
                    venue=venue,
                    price_cents=price,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    qualification=qualification,
                    is_unconditional=is_unconditional,
                )
            )
        return tuple(rows)
