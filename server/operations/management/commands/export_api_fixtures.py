from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from billing.models import AccountEntitlement
from covers.models import CoverDecision
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test import Client
from identity.models import Account
from identity.tokens import issue_session_token

from operations.management.commands.seed_visual_acceptance import fixture_uuid


def fixture_now() -> datetime:
    value = getattr(settings, "VISUAL_ACCEPTANCE_NOW", None)
    if not isinstance(value, datetime):
        raise CommandError("canonical fixture settings require a fixed aware clock")
    return value


class FixtureClient:
    def __init__(self, profile: str):
        self.profile = profile
        self.client = Client()

    def get(self, path: str, params=None, *, headers=None, expected_status: int = 200):
        response = self.client.get(path, params or {}, headers=headers or {})
        if response.status_code != expected_status:
            raise CommandError(
                f"fixture endpoint {path} returned {response.status_code}, "
                f"expected {expected_status}"
            )
        self._stabilize_decisions()
        if CoverDecision.objects.exists() and expected_status == 200:
            response = self.client.get(path, params or {}, headers=headers or {})
            if response.status_code != expected_status:
                raise CommandError(f"fixture endpoint {path} changed status after stabilization")
        return response

    def get_premium_time_machine(self, venue: str):
        account = Account.objects.create_user(
            email="fixture-premium@example.invalid",
            id=fixture_uuid(f"account:{self.profile}:premium"),
        )
        AccountEntitlement.objects.create(
            account=account,
            environment=AccountEntitlement.Environment.SANDBOX,
            is_active=True,
        )
        session = SessionStore()
        session[SESSION_KEY] = str(account.pk)
        session[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
        session[HASH_SESSION_KEY] = account.get_session_auth_hash()
        session.save()
        token = issue_session_token(session)
        target = fixture_now().isoformat()
        response = self.client.get(
            f"/api/v2/venues/{venue}/cover/time-machine",
            {"target_time": target},
            headers={"X-Session-Token": token},
        )
        if response.status_code != 200:
            raise CommandError(f"premium fixture returned {response.status_code}")
        self._stabilize_decisions()
        return self.client.get(
            f"/api/v2/venues/{venue}/cover/time-machine",
            {"target_time": target},
            headers={"X-Session-Token": token},
        )

    def _stabilize_decisions(self) -> None:
        decisions = list(CoverDecision.objects.select_related("venue").order_by("venue__slug"))
        for decision in decisions:
            stable_id = fixture_uuid(
                ":".join(
                    (
                        "decision",
                        self.profile,
                        decision.venue.slug,
                        decision.target_time.isoformat(),
                        decision.knowledge_cutoff.isoformat(),
                    )
                )
            )
            if decision.pk != stable_id:
                CoverDecision.objects.filter(pk=decision.pk).update(id=stable_id)


class Command(BaseCommand):
    help = "Export deterministic, backend-owned canonical API fixtures."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        self._guard()
        output = Path(options["output"]).resolve()
        output.mkdir(parents=True, exist_ok=True)

        rich = self._seed("cover-states")
        self._write_response(output / "cover-board-rich.json", rich.get("/api/v2/cover"))
        self._write_response(output / "deals-rich.json", rich.get("/api/v2/deals"))
        self._write_response(
            output / "venue-cover-rich.json", rich.get("/api/v2/venues/live/cover")
        )
        self._write_response(
            output / "venue-cover-history-rich.json",
            rich.get("/api/v2/venues/live/cover/history"),
        )
        self._write_response(
            output / "venue-cover-no-current-reports.json",
            rich.get("/api/v2/venues/unavailable/cover"),
        )
        self._write_response(
            output / "venue-cover-older-history.json",
            rich.get("/api/v2/venues/unavailable/cover/history"),
        )
        self._write_response(
            output / "deal-suggestions-rich.json",
            rich.get(
                "/api/v2/deal-suggestions",
                {"q": "happy", "venue": "live", "limit": 6},
            ),
        )
        self._write_response(
            output / "venue-not-found-error.json",
            rich.get(
                "/api/v2/venues/not-a-real-venue/cover",
                # A canonical UUIDv4 keeps the checked-in error fixture
                # deterministic without weakening the production log boundary.
                headers={"X-Request-ID": "00000000-0000-4000-8000-000000000001"},
                expected_status=404,
            ),
        )

        historical = self._seed("historical")
        self._write_response(
            output / "cover-board-historical.json", historical.get("/api/v2/cover")
        )
        self._write_response(
            output / "time-machine-premium.json",
            historical.get_premium_time_machine("live"),
        )

        empty = self._seed("empty")
        self._write_response(output / "cover-board-empty.json", empty.get("/api/v2/cover"))
        self._write_response(output / "deals-empty.json", empty.get("/api/v2/deals"))

        catalog = {
            "schemaVersion": 1,
            "fixedNow": fixture_now().isoformat(),
            "scenarios": {
                "normal": {"cover": "cover-board-rich.json", "deals": "deals-rich.json"},
                "sparse": {"cover": "cover-board-historical.json"},
                "conflicting": {"cover": "cover-board-rich.json", "venueSlug": "mixed"},
                "empty": {"cover": "cover-board-empty.json", "deals": "deals-empty.json"},
                "premium": {"timeMachine": "time-machine-premium.json"},
                "error": {"response": "venue-not-found-error.json", "status": 404},
                "offlineSubmission": {
                    "prime": ["cover-board-rich.json", "deals-rich.json"],
                    "transport": "offline",
                    "expectedDisposition": "queued",
                },
                "stale": {
                    "prime": ["cover-board-rich.json", "deals-rich.json"],
                    "advanceClockSeconds": 3601,
                    "transport": "offline",
                },
            },
        }
        self._write_json(output / "catalog.json", catalog)
        self.stdout.write(self.style.SUCCESS(f"exported canonical fixtures to {output}"))

    def _guard(self) -> None:
        if not getattr(settings, "CANONICAL_FIXTURE_EXPORT", False):
            raise CommandError("config.settings.fixtures is required")
        if connection.vendor != "sqlite":
            raise CommandError("canonical fixture export requires SQLite")
        expected = (
            settings.REPOSITORY_DIR
            / ".local"
            / "visual-acceptance"
            / "canonical-fixtures.sqlite3"
        ).resolve()
        configured = Path(connection.settings_dict["NAME"]).resolve()
        if configured != expected:
            raise CommandError("canonical fixture database is outside its exact safe boundary")

    def _seed(self, profile: str) -> FixtureClient:
        call_command("flush", interactive=False, verbosity=0)
        call_command(
            "seed_visual_acceptance",
            profile=profile,
            at=fixture_now().isoformat(),
            verbosity=0,
        )
        return FixtureClient(profile)

    def _write_response(self, path: Path, response) -> None:
        body = response.json()
        self._write_json(path, body)

    def _write_json(self, path: Path, value) -> None:
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
