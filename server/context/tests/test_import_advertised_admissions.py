import json
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from operations.models import JobRun
from venues.models import Venue

from context.models import AdvertisedAdmission, SourceFetch


@pytest.mark.django_db
def test_reviewed_advertised_admission_import_is_provenanced_and_idempotent(tmp_path):
    Venue.objects.create(slug="kams", name="KAMS")
    fetched_at = timezone.now().replace(microsecond=0)
    document = tmp_path / "admissions.json"
    document.write_text(
        json.dumps(
            {
                "admissions": [
                    {
                        "venueSlug": "kams",
                        "priceCents": 2_000,
                        "startsAt": (fetched_at + timedelta(minutes=5)).isoformat(),
                        "endsAt": (fetched_at + timedelta(hours=2)).isoformat(),
                        "qualification": "",
                        "isUnconditional": True,
                    },
                    {
                        "venueSlug": "kams",
                        "priceCents": 1_000,
                        "startsAt": (fetched_at + timedelta(minutes=5)).isoformat(),
                        "endsAt": (fetched_at + timedelta(hours=2)).isoformat(),
                        "qualification": "21+ only",
                        "isUnconditional": False,
                    },
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    options = {
        "source_identifier": "venue-published-site",
        "source_url": "https://example.invalid/admission",
        "fetched_at": fetched_at.isoformat(),
        "external_key": "kams-2026-08-12",
        "parser_version": "review-v1",
        "verbosity": 0,
    }

    call_command("import_advertised_admissions", str(document), **options)
    call_command("import_advertised_admissions", str(document), **options)

    assert SourceFetch.objects.count() == 1
    assert AdvertisedAdmission.objects.count() == 2
    assert AdvertisedAdmission.objects.get(is_unconditional=True).qualification == ""
    summaries = list(
        JobRun.objects.filter(name="import_advertised_admissions").values_list(
            "result_summary", flat=True
        )
    )
    assert [summary["rowsCreated"] for summary in summaries] == [2, 0]


@pytest.mark.django_db
def test_advertised_import_rejects_conditional_fact_marked_unconditional(tmp_path):
    Venue.objects.create(slug="kams", name="KAMS")
    fetched_at = timezone.now().replace(microsecond=0)
    document = tmp_path / "invalid.json"
    document.write_text(
        json.dumps(
            {
                "admissions": [
                    {
                        "venueSlug": "kams",
                        "priceCents": 1_000,
                        "startsAt": (fetched_at + timedelta(minutes=1)).isoformat(),
                        "qualification": "21+ only",
                        "isUnconditional": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CommandError, match="cannot be unconditional"):
        call_command(
            "import_advertised_admissions",
            str(document),
            source_identifier="venue-published-site",
            source_url="https://example.invalid/admission",
            fetched_at=fetched_at.isoformat(),
            external_key="invalid",
            verbosity=0,
        )

    assert not SourceFetch.objects.exists()
    assert not AdvertisedAdmission.objects.exists()
