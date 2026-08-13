import hashlib
import json
import uuid
from datetime import date

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test.utils import CaptureQueriesContext
from operations.models import DatasetImportRun
from venues.models import Venue

from deals.models import DealFamily, HistoricalDealFact


def write_release(tmp_path, release_name: str, rows: list[dict]) -> tuple[str, str]:
    release_dir = tmp_path / release_name
    release_dir.mkdir()
    dataset = release_dir / "facts.jsonl"
    dataset.write_text("".join(f"{json.dumps(row, sort_keys=True)}\n" for row in rows))
    content_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()
    manifest = release_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "dataset_release": release_name,
                "schema_version": 1,
                "artifacts": [
                    {
                        "path": dataset.name,
                        "rows": len(rows),
                        "sha256": content_hash,
                    }
                ],
            }
        )
    )
    return str(manifest), str(dataset)


def deal_row(index: int, *, price_cents: int = 300) -> dict:
    family_index = index % 5
    return {
        "canonical_family": f"family_{family_index}",
        "canonical_family_source_id": f"family-source-{family_index}",
        "category": "drink",
        "display_name": f"Deal {index}",
        "raw_name": f"Raw Deal Alias {index}",
        "price_amount_cents": price_cents,
        "price_kind": "single",
        "price_relative_percent": None,
        "service_date": "2026-08-12",
        "source_post_key": f"post-{index}",
        "source_record_key": f"record-{index}",
        "timing_end_local": None,
        "timing_kind": "unknown",
        "timing_start_local": None,
        "timing_time_local": None,
        "unit": None,
        "venue_slug": "bulk-test",
        "while_supplies_last": False,
    }


@pytest.mark.django_db(transaction=True)
def test_deal_dataset_import_uses_bounded_queries_and_is_idempotent(tmp_path):
    Venue.objects.create(slug="bulk-test", name="Bulk Test")
    rows = [deal_row(index) for index in range(30)]
    manifest, dataset = write_release(tmp_path, "bulk-query-test", rows)

    with CaptureQueriesContext(connection) as first_queries:
        call_command(
            "import_deal_dataset",
            manifest=manifest,
            dataset=dataset,
            verbosity=0,
        )

    assert len(first_queries) <= 20
    fact_inserts = [
        query
        for query in first_queries
        if 'INSERT INTO "deals_historicaldealfact"' in query["sql"]
    ]
    assert len(fact_inserts) == 1
    assert HistoricalDealFact.objects.count() == 30
    assert HistoricalDealFact.objects.get(
        source_record_key="record-1"
    ).private_search_text == (
        "raw deal alias 1"
    )
    assert DealFamily.objects.count() == 5
    expected_namespace = uuid.uuid5(
        uuid.NAMESPACE_URL, "https://illinicover.com/deal-families"
    )
    assert DealFamily.objects.get(source_identifier="family-source-0").pk == uuid.uuid5(
        expected_namespace, "family-source-0"
    )
    first_run = DatasetImportRun.objects.get()
    assert (first_run.rows_seen, first_run.rows_accepted) == (30, 30)

    with CaptureQueriesContext(connection) as replay_queries:
        call_command(
            "import_deal_dataset",
            manifest=manifest,
            dataset=dataset,
            verbosity=0,
        )

    assert len(replay_queries) <= 12
    assert not any(
        'INSERT INTO "deals_historicaldealfact"' in query["sql"] for query in replay_queries
    )
    assert HistoricalDealFact.objects.count() == 30
    replay_run = DatasetImportRun.objects.order_by("-id").first()
    assert replay_run is not None
    assert (replay_run.rows_seen, replay_run.rows_accepted) == (30, 0)


@pytest.mark.django_db(transaction=True)
def test_existing_fact_conflict_keeps_first_immutable_payload(tmp_path):
    Venue.objects.create(slug="bulk-test", name="Bulk Test")
    original_manifest, original_dataset = write_release(
        tmp_path, "fact-conflict-original", [deal_row(1, price_cents=300)]
    )
    call_command(
        "import_deal_dataset",
        manifest=original_manifest,
        dataset=original_dataset,
        verbosity=0,
    )

    conflicting_manifest, conflicting_dataset = write_release(
        tmp_path, "fact-conflict-replay", [deal_row(1, price_cents=9_999)]
    )
    call_command(
        "import_deal_dataset",
        manifest=conflicting_manifest,
        dataset=conflicting_dataset,
        verbosity=0,
    )

    fact = HistoricalDealFact.objects.get(source_record_key="record-1")
    assert fact.price_cents == 300
    replay_run = DatasetImportRun.objects.order_by("-id").first()
    assert replay_run is not None
    assert (replay_run.rows_seen, replay_run.rows_accepted) == (1, 0)


@pytest.mark.django_db(transaction=True)
def test_deal_dataset_import_stores_product_name_separately_from_raw_and_structured_price(
    tmp_path,
):
    Venue.objects.create(slug="bulk-test", name="Bulk Test")
    row = deal_row(1)
    row["display_name"] = "$3 Deal 1"
    row["raw_name"] = "$3 Deal 1 after ten"
    manifest, dataset = write_release(tmp_path, "product-name-test", [row])

    call_command(
        "import_deal_dataset",
        manifest=manifest,
        dataset=dataset,
        verbosity=0,
    )

    fact = HistoricalDealFact.objects.get(source_record_key="record-1")
    assert fact.display_name == "Deal 1"
    assert fact.price_cents == 300
    assert fact.private_search_text == "3 deal 1 after ten"


@pytest.mark.django_db(transaction=True)
def test_deal_dataset_import_rejects_a_display_name_that_is_only_the_structured_price(
    tmp_path,
):
    Venue.objects.create(slug="bulk-test", name="Bulk Test")
    row = deal_row(1)
    row["display_name"] = "$3"
    manifest, dataset = write_release(tmp_path, "missing-product-name-test", [row])

    with pytest.raises(CommandError, match="record-1 has no product display name"):
        call_command(
            "import_deal_dataset",
            manifest=manifest,
            dataset=dataset,
            verbosity=0,
        )

    assert HistoricalDealFact.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_search_alias_migration_backfills_an_existing_imported_fact(
    settings, monkeypatch, tmp_path
):
    executor = MigrationExecutor(connection)
    executor.migrate([("deals", "0007_dealevidenceevent_target_evidence")])
    old_apps = executor.loader.project_state(
        [("deals", "0007_dealevidenceevent_target_evidence")]
    ).apps
    venue = old_apps.get_model("venues", "Venue").objects.create(
        slug="bulk-test", name="Bulk Test"
    )
    old_apps.get_model("deals", "HistoricalDealFact").objects.create(
        source_record_key="record-existing",
        source_dataset="test",
        venue=venue,
        display_name="Long Island Iced Tea",
        category="drink",
        price_kind="single",
        price_cents=500,
        service_date_local="2026-08-12",
        timing_kind="unknown",
        source_post_key="post-existing",
        source_payload_hash="a" * 64,
    )
    release = tmp_path / "data" / "deals" / "historical-deals-v1"
    release.mkdir(parents=True)
    (release / "historical-deals-v1.jsonl").write_text(
        json.dumps(
            {
                "source_record_key": "record-existing",
                "raw_name": "Lit Pitcher",
            }
        )
        + "\n"
    )
    monkeypatch.setattr(settings, "REPOSITORY_DIR", tmp_path)

    executor = MigrationExecutor(connection)
    executor.migrate([("deals", "0008_historicaldealfact_search_alias")])
    new_apps = executor.loader.project_state(
        [("deals", "0008_historicaldealfact_search_alias")]
    ).apps
    fact = new_apps.get_model("deals", "HistoricalDealFact").objects.get(
        source_record_key="record-existing"
    )
    assert fact.private_search_text == "lit pitcher"


@pytest.mark.django_db(transaction=True)
def test_prediction_rank_migration_backfills_existing_release_order():
    previous = ("deals", "0008_historicaldealfact_search_alias")
    latest = ("deals", "0009_dealprediction_rank")
    executor = MigrationExecutor(connection)
    executor.migrate([previous])
    old_apps = executor.loader.project_state([previous]).apps
    venue = old_apps.get_model("venues", "Venue").objects.create(
        slug="rank-migration", name="Rank Migration"
    )
    family_model = old_apps.get_model("deals", "DealFamily")
    definition_model = old_apps.get_model("deals", "DealDefinition")
    prediction_model = old_apps.get_model("deals", "DealPrediction")
    release = old_apps.get_model("deals", "DealPredictionRelease").objects.create(
        predictor_version="rank-migration",
        code_revision="rank-migration",
        training_data_revision="rank-migration",
    )
    expected = []

    try:
        for index, (support_nights, latest_evidence_date) in enumerate(
            ((2, date(2026, 8, 10)), (5, date(2026, 8, 9)), (2, date(2026, 8, 11))),
            start=1,
        ):
            family = family_model.objects.create(
                canonical_name=f"Migration family {index}", category="drink"
            )
            definition = definition_model.objects.create(
                venue=venue,
                family=family,
                display_name=f"Migration deal {index}",
                category="drink",
                price_kind="single",
            )
            prediction = prediction_model.objects.create(
                release=release,
                venue=venue,
                deal_definition=definition,
                service_date_local="2026-08-12",
                support_nights=support_nights,
                comparable_nights=5,
                latest_evidence_date=latest_evidence_date,
            )
            expected.append((prediction.pk, support_nights, latest_evidence_date))

        executor = MigrationExecutor(connection)
        executor.migrate([latest])
        migrated_apps = executor.loader.project_state([latest]).apps
        migrated = migrated_apps.get_model("deals", "DealPrediction")
        actual = list(
            migrated.objects.filter(release_id=release.pk)
            .order_by("rank")
            .values_list("id", flat=True)
        )
        expected_ids = [
            row[0]
            for row in sorted(
                expected,
                key=lambda row: (-row[1], -row[2].toordinal(), str(row[0])),
            )
        ]
        assert actual == expected_ids
        assert list(
            migrated.objects.filter(release_id=release.pk)
            .order_by("rank")
            .values_list("rank", flat=True)
        ) == [1, 2, 3]
    finally:
        MigrationExecutor(connection).migrate([latest])
