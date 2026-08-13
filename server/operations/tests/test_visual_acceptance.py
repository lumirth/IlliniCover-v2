import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import Client, override_settings
from django.utils import timezone


@pytest.mark.django_db
@pytest.mark.skipif(
    connection.vendor != "sqlite",
    reason="this test exercises the repository-bounded SQLite acceptance seeder",
)
@override_settings(VISUAL_ACCEPTANCE=True, DEBUG=True)
def test_visual_acceptance_cover_profile_exercises_public_wire_contract(settings):
    allowed = (settings.REPOSITORY_DIR / ".local" / "visual-acceptance").resolve()
    allowed.mkdir(parents=True, exist_ok=True)
    original_name = connection.settings_dict["NAME"]
    connection.settings_dict["NAME"] = allowed / "pytest.sqlite3"
    try:
        call_command(
            "seed_visual_acceptance",
            profile="cover-states",
            at=timezone.now().isoformat(),
            verbosity=0,
        )
    finally:
        connection.settings_dict["NAME"] = original_name

    board = Client().get("/api/v2/cover").json()["venues"]
    sources = {row["venue"]["slug"]: row["cover"]["source"] for row in board}
    assert sources["live"] == "live"
    assert sources["mixed"] == "mixed"
    assert sources["unconfirmed"] == "unconfirmed"
    assert sources["advertised"] == "advertised"
    assert sources["advertised-range"] == "mixed"
    assert sources["unavailable"] == "unavailable"
    advertised_range = next(row for row in board if row["venue"]["slug"] == "advertised-range")[
        "cover"
    ]
    assert advertised_range["status"] == "advertised_conflict"
    assert advertised_range["price"] == {
        "kind": "range",
        "amountCents": None,
        "lowCents": 500,
        "highCents": 1_500,
    }
    assert (
        next(row for row in board if row["venue"]["slug"] == "live")["latestActivityAt"] is not None
    )
    assert (
        next(row for row in board if row["venue"]["slug"] == "unavailable")["latestActivityAt"]
        is None
    )
    reports = Client().get("/api/v2/venues/live/cover").json()["recentReports"]
    assert len(reports) > 4
    assert any(
        report["priceCents"] is None and report["interaction"] == "vibes" for report in reports
    )

    deals = Client().get("/api/v2/deals").json()["venues"]
    assert any(row["deals"] for row in deals)
    assert any(not row["deals"] for row in deals)
    assert any(
        deal["unit"] == "" and deal["servingFormat"] == ""
        for venue in deals
        for deal in venue["deals"]
    )
    visible = {
        venue["venue"]["name"]: [deal["displayName"] for deal in venue["deals"]] for venue in deals
    }
    assert visible["KAMS"] == ["White Claw"]
    assert visible["Joe's"] == ["Michelob Ultra"]
    assert visible["Red Lion"] == ["Bombs"]
    assert visible["Brothers"] == ["Wells", "Busch Light", "Big Cups"]
    suggestions = (
        Client()
        .get("/api/v2/deal-suggestions", {"q": "happy", "venue": "live", "limit": 6})
        .json()["suggestions"]
    )
    assert len(suggestions) == 6
    assert {row["matchedSource"] for row in suggestions} == {"alias"}
    assert [row["sourceScope"] for row in suggestions] == [
        "venue",
        "venue",
        "venue",
        "global",
        "global",
        "global",
    ]
    assert all(
        not row["displayName"].lstrip().startswith("$") for row in suggestions
    )
    assert any(len(row["displayName"]) > 60 for row in suggestions)


@pytest.mark.django_db
@pytest.mark.skipif(
    connection.vendor != "sqlite",
    reason="this test exercises the repository-bounded SQLite acceptance seeder",
)
@override_settings(VISUAL_ACCEPTANCE=True, DEBUG=True)
def test_visual_acceptance_historical_profile_matches_the_clean_v1_comparison_state(settings):
    allowed = (settings.REPOSITORY_DIR / ".local" / "visual-acceptance").resolve()
    allowed.mkdir(parents=True, exist_ok=True)
    original_name = connection.settings_dict["NAME"]
    connection.settings_dict["NAME"] = allowed / "pytest-historical.sqlite3"
    try:
        call_command(
            "seed_visual_acceptance",
            profile="historical",
            at=timezone.now().isoformat(),
            verbosity=0,
        )
    finally:
        connection.settings_dict["NAME"] = original_name

    board = Client().get("/api/v2/cover").json()["venues"]
    prices = {row["venue"]["name"]: row["cover"]["price"].get("amountCents") for row in board}
    assert prices["KAMS"] == 1_000
    assert prices["Joe's"] == 1_000
    assert prices["Red Lion"] == 1_000
    assert prices["Brothers"] == 500
    assert prices["A Deliberately Very Long Venue Name for Layout Verification"] == 1_200


@pytest.mark.django_db
@pytest.mark.skipif(
    connection.vendor != "sqlite",
    reason="this test exercises the repository-bounded SQLite acceptance seeder",
)
@override_settings(VISUAL_ACCEPTANCE=True, DEBUG=True)
def test_visual_acceptance_seeder_refuses_a_non_acceptance_database(settings):
    original_name = connection.settings_dict["NAME"]
    connection.settings_dict["NAME"] = Path("/tmp/not-illinicover-visual.sqlite3")
    try:
        with pytest.raises(CommandError, match="outside the allowed root"):
            call_command(
                "seed_visual_acceptance",
                profile="empty",
                at=timezone.now().isoformat(),
                verbosity=0,
            )
    finally:
        connection.settings_dict["NAME"] = original_name


def test_visual_acceptance_settings_refuse_without_explicit_opt_in():
    environment = os.environ.copy()
    environment.pop("VISUAL_ACCEPTANCE_ENABLED", None)
    environment.pop("DATABASE_URL", None)
    environment.pop("DATABASE_URL_DIRECT", None)
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings.visual_acceptance"],
        cwd=Path(__file__).resolve().parents[3] / "server",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "VISUAL_ACCEPTANCE_ENABLED=1 is required" in result.stderr


def test_visual_acceptance_settings_refuse_external_database_urls(tmp_path):
    environment = os.environ.copy()
    environment["VISUAL_ACCEPTANCE_ENABLED"] = "1"
    environment["DATABASE_URL"] = "postgresql://example.invalid/database"
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings.visual_acceptance"],
        cwd=Path(__file__).resolve().parents[3] / "server",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "refuses external database URLs" in result.stderr


def test_visual_acceptance_settings_refuse_cloud_run():
    environment = os.environ.copy()
    environment["VISUAL_ACCEPTANCE_ENABLED"] = "1"
    environment["K_SERVICE"] = "illinicover-api"
    environment.pop("DATABASE_URL", None)
    environment.pop("DATABASE_URL_DIRECT", None)
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings.visual_acceptance"],
        cwd=Path(__file__).resolve().parents[3] / "server",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "refuse Cloud Run" in result.stderr


def test_visual_acceptance_settings_refuse_uncorrelated_source_revision():
    environment = os.environ.copy()
    environment["VISUAL_ACCEPTANCE_ENABLED"] = "1"
    environment["CODE_REVISION"] = "development"
    environment.pop("DATABASE_URL", None)
    environment.pop("DATABASE_URL_DIRECT", None)
    for marker in ("K_SERVICE", "K_REVISION", "CLOUD_RUN_JOB", "CLOUD_RUN_EXECUTION"):
        environment.pop(marker, None)
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings.visual_acceptance"],
        cwd=Path(__file__).resolve().parents[3] / "server",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "exact src-<sha256> CODE_REVISION" in result.stderr


@override_settings(
    VISUAL_ACCEPTANCE=True,
    VISUAL_ACCEPTANCE_FAULT={
        "method": "GET",
        "path_prefix": "/api/v2/cover",
        "status": 503,
        "delay_ms": 0,
    },
    MIDDLEWARE=[
        "config.middleware.RequestIdMiddleware",
        "config.visual_acceptance.VisualAcceptanceFaultMiddleware",
    ],
)
def test_visual_acceptance_fault_middleware_is_path_bounded():
    client = Client()
    fault = client.get("/api/v2/cover")
    unaffected = client.get("/health/live")
    assert fault.status_code == 503
    assert fault.json()["code"] == "visual_acceptance_fault"
    assert unaffected.status_code == 200


@override_settings(
    VISUAL_ACCEPTANCE=True,
    VISUAL_ACCEPTANCE_NOW=timezone.now(),
    VISUAL_ACCEPTANCE_FAULT=None,
    MIDDLEWARE=[
        "config.middleware.RequestIdMiddleware",
        "config.visual_acceptance.VisualAcceptanceFaultMiddleware",
    ],
)
def test_visual_acceptance_fixed_clock_is_read_only():
    client = Client()
    assert client.get("/health/live").status_code == 200
    blocked = client.post("/api/v2/installations", data={}, content_type="application/json")
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "visual_acceptance_fixed_clock_read_only"


def test_visual_acceptance_settings_parse_fixed_clock_and_delay_fault(tmp_path):
    environment = os.environ.copy()
    environment["VISUAL_ACCEPTANCE_ENABLED"] = "1"
    environment["CODE_REVISION"] = "src-" + "a" * 64
    environment["VISUAL_ACCEPTANCE_NOW"] = "2026-08-12T20:00:00-05:00"
    environment["VISUAL_ACCEPTANCE_FAULT"] = "GET:/api/v2/deals:pass:2500"
    environment.pop("DATABASE_URL", None)
    environment.pop("DATABASE_URL_DIRECT", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from config.settings.visual_acceptance import "
                "VISUAL_ACCEPTANCE_FAULT, VISUAL_ACCEPTANCE_NOW; "
                "print(VISUAL_ACCEPTANCE_NOW.isoformat(), VISUAL_ACCEPTANCE_FAULT)"
            ),
        ],
        cwd=Path(__file__).resolve().parents[3] / "server",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "2026-08-12T20:00:00-05:00" in result.stdout
    assert "'status': None" in result.stdout
    assert "'delay_ms': 2500" in result.stdout
