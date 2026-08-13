import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

REPOSITORY = Path(__file__).resolve().parents[3]


def test_fixture_export_refuses_ordinary_test_settings(tmp_path):
    with pytest.raises(CommandError, match="config.settings.fixtures is required"):
        call_command("export_api_fixtures", output=tmp_path, verbosity=0)


def test_checked_in_fixture_catalog_covers_required_product_states():
    fixture_root = REPOSITORY / "api" / "fixtures"
    catalog = json.loads((fixture_root / "catalog.json").read_text(encoding="utf-8"))
    assert set(catalog["scenarios"]) == {
        "normal",
        "sparse",
        "conflicting",
        "stale",
        "error",
        "empty",
        "premium",
        "offlineSubmission",
    }
    for scenario in catalog["scenarios"].values():
        for value in scenario.values():
            names = value if isinstance(value, list) else [value]
            for name in names:
                if isinstance(name, str) and name.endswith(".json"):
                    assert (fixture_root / name).is_file()

    board = json.loads((fixture_root / "cover-board-rich.json").read_text(encoding="utf-8"))
    sources = {row["venue"]["slug"]: row["cover"]["source"] for row in board["venues"]}
    assert sources == {
        "live": "live",
        "mixed": "mixed",
        "unconfirmed": "unconfirmed",
        "advertised": "advertised",
        "advertised-range": "mixed",
        "unavailable": "unavailable",
        "overflow": "live",
    }

    deals = json.loads((fixture_root / "deals-rich.json").read_text(encoding="utf-8"))
    brothers = next(row for row in deals["venues"] if row["venue"]["name"] == "Brothers")
    assert [deal["displayName"] for deal in brothers["deals"]] == [
        "Wells",
        "Busch Light",
        "Big Cups",
    ]
    assert all(
        not deal["displayName"].lstrip().startswith("$")
        for venue in deals["venues"]
        for deal in venue["deals"]
    )

    suggestions = json.loads(
        (fixture_root / "deal-suggestions-rich.json").read_text(encoding="utf-8")
    )["suggestions"]
    assert all(
        not suggestion["displayName"].lstrip().startswith("$")
        for suggestion in suggestions
    )

    no_current = json.loads(
        (fixture_root / "venue-cover-no-current-reports.json").read_text(encoding="utf-8")
    )
    older_history = json.loads(
        (fixture_root / "venue-cover-older-history.json").read_text(encoding="utf-8")
    )
    assert no_current["recentReports"] == []
    assert older_history["accessTier"] == "limited"
    assert len(older_history["reports"]) == 1


def test_fixture_settings_refuse_external_or_deployed_state():
    environment = os.environ.copy()
    environment["DATABASE_URL"] = "postgresql://example.invalid/production"
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings.fixtures"],
        cwd=REPOSITORY / "server",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "refuses deployed or external state" in result.stderr
