import pytest
from covers.models import CoverModelRelease, CoverObservation
from deals.models import DealPredictionRelease, HistoricalDealFact
from django.contrib.sites.models import Site
from django.core.management import call_command
from django.test import Client, override_settings
from django.utils import timezone
from handbook.models import HandbookPage
from submissions.models import Submission
from venues.models import Venue

from operations.models import DatasetImportRun, DatasetRelease


@pytest.mark.django_db(transaction=True)
def test_versioned_imports_are_hash_checked_receipted_and_idempotent():
    call_command("import_venues", verbosity=0)
    call_command("import_cover_dataset", verbosity=0)
    call_command("import_deal_dataset", verbosity=0)

    assert Venue.objects.count() == 4
    assert CoverObservation.objects.count() == 1199
    assert HistoricalDealFact.objects.count() == 13786
    assert HistoricalDealFact.objects.filter(
        private_search_text="lit pitcher",
        display_name="Long Island Iced Tea",
    ).exists()
    alias_results = Client().get(
        "/api/v2/deal-suggestions",
        {"q": "Lit Pitcher", "venue": "brothers", "limit": 6},
    ).json()["suggestions"]
    assert any(
        row["displayName"] == "Long Island Iced Tea"
        and row["matchedSource"] == "historical_alias"
        and row["matchedText"] is None
        for row in alias_results
    )
    assert DatasetRelease.objects.count() == 3
    assert DatasetImportRun.objects.filter(result="succeeded").count() == 3
    assert Submission.objects.filter(source_kind="dataset_import").count() == 1199

    call_command("import_venues", verbosity=0)
    call_command("import_cover_dataset", verbosity=0)
    call_command("import_deal_dataset", verbosity=0)

    assert Venue.objects.count() == 4
    assert CoverObservation.objects.count() == 1199
    assert HistoricalDealFact.objects.count() == 13786
    latest_runs = DatasetImportRun.objects.order_by("-id")[:3]
    assert all(run.rows_accepted == 0 for run in latest_runs)


@pytest.mark.django_db(transaction=True)
@override_settings(PUBLIC_API_ORIGIN="https://illinicover-api-example.run.app")
def test_beta_bootstrap_replays_from_blank_database_without_duplicates():
    call_command("bootstrap_beta", verbosity=0)
    call_command("bootstrap_beta", verbosity=0)

    assert Venue.objects.count() == 4
    assert CoverObservation.objects.count() == 1199
    assert HistoricalDealFact.objects.count() == 13786
    assert Site.objects.get(pk=1).domain == "illinicover-api-example.run.app"
    assert HandbookPage.objects.filter(status="published").count() == 1
    assert DealPredictionRelease.objects.filter(is_authoritative=True).count() == 1


@pytest.mark.django_db(transaction=True)
@override_settings(PUBLIC_API_ORIGIN="https://illinicover-api-example.run.app")
def test_beta_bootstrap_replay_preserves_a_promoted_challenger():
    call_command("bootstrap_beta", verbosity=0)
    initial = CoverModelRelease.objects.get(model_version="cover_historical_v1")
    authority_changed_at = timezone.now()
    CoverModelRelease.objects.filter(pk=initial.pk).update(
        is_authoritative=False,
        retired_at=authority_changed_at,
    )
    challenger = CoverModelRelease.objects.create(
        model_kind="historical_challenger",
        model_version="accepted-challenger",
        code_revision="accepted-challenger-code",
        training_data_revision=initial.training_data_revision,
        parameters_or_artifact=initial.parameters_or_artifact,
        evaluation_metrics={"status": "accepted"},
        is_authoritative=True,
        promoted_at=authority_changed_at,
    )

    call_command("bootstrap_beta", verbosity=0)

    initial.refresh_from_db()
    challenger.refresh_from_db()
    assert initial.is_authoritative is False
    assert initial.retired_at == authority_changed_at
    assert challenger.is_authoritative is True
    assert challenger.promoted_at == authority_changed_at
    assert challenger.retired_at is None
    assert CoverModelRelease.objects.filter(is_authoritative=True).count() == 1
