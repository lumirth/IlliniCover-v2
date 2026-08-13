import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, connection, transaction
from operations.imports import import_run, jsonl_rows, open_release
from venues.models import Venue

from deals.models import DealFamily, HistoricalDealFact
from deals.names import public_deal_name
from deals.search import normalize_deal_search_text

DEFAULT_RELEASE = settings.REPOSITORY_DIR / "data" / "deals" / "historical-deals-v1"
FAMILY_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://illinicover.com/deal-families")
READ_BATCH_SIZE = 5_000
BULK_CREATE_BATCH_SIZE = 2_000


@dataclass(frozen=True, slots=True)
class FamilyInput:
    source_identifier: str
    canonical_name: str
    category: str


@dataclass(frozen=True, slots=True)
class FactInput:
    source_record_key: str
    venue_id: uuid.UUID
    family_source_identifier: str | None
    private_search_text: str
    display_name: str
    category: str
    price_kind: str
    price_cents: int | None
    relative_percent: int | float | None
    unit: str
    service_date_local: str
    timing_kind: str
    timing_start_local: time | None
    timing_end_local: time | None
    timing_time_local: time | None
    while_supplies_last: bool
    source_post_key: str
    source_payload_hash: str


def parse_time(value: str | None):
    return time.fromisoformat(value) if value else None


def read_batches(values: list[str]):
    database_limit = connection.features.max_query_params
    batch_size = min(READ_BATCH_SIZE, database_limit or READ_BATCH_SIZE)
    for start in range(0, len(values), batch_size):
        yield values[start : start + batch_size]


def load_families(source_identifiers: list[str]) -> dict[str, DealFamily]:
    families: dict[str, DealFamily] = {}
    for batch in read_batches(source_identifiers):
        for family in DealFamily.objects.filter(source_identifier__in=batch):
            if family.source_identifier is not None:
                families[family.source_identifier] = family
    return families


def ensure_families(inputs: dict[str, FamilyInput]) -> dict[str, DealFamily]:
    families = load_families(list(inputs))
    missing = [item for source_id, item in inputs.items() if source_id not in families]
    if not missing:
        return families

    candidates = [
        DealFamily(
            id=uuid.uuid5(FAMILY_NAMESPACE, item.source_identifier),
            source_identifier=item.source_identifier,
            canonical_name=item.canonical_name,
            category=item.category,
        )
        for item in missing
    ]
    try:
        # Keep the common path bulk-only while preserving get_or_create's behavior
        # if another importer wins a uniqueness race between our read and write.
        with transaction.atomic():
            DealFamily.objects.bulk_create(
                candidates,
                batch_size=BULK_CREATE_BATCH_SIZE,
            )
    except IntegrityError:
        for item in missing:
            family, _ = DealFamily.objects.get_or_create(
                source_identifier=item.source_identifier,
                defaults={
                    "id": uuid.uuid5(FAMILY_NAMESPACE, item.source_identifier),
                    "canonical_name": item.canonical_name,
                    "category": item.category,
                },
            )
            families[item.source_identifier] = family
    else:
        families.update(
            (candidate.source_identifier, candidate)
            for candidate in candidates
            if candidate.source_identifier is not None
        )
    return families


def existing_fact_keys(source_record_keys: list[str]) -> set[str]:
    existing: set[str] = set()
    for batch in read_batches(source_record_keys):
        existing.update(
            HistoricalDealFact.objects.filter(source_record_key__in=batch).values_list(
                "source_record_key", flat=True
            )
        )
    return existing


def fact_defaults(
    item: FactInput,
    *,
    release_name: str,
    families: dict[str, DealFamily],
) -> dict[str, object]:
    family = (
        families[item.family_source_identifier]
        if item.family_source_identifier is not None
        else None
    )
    return {
        "source_dataset": release_name,
        "venue_id": item.venue_id,
        "family_id": family.pk if family is not None else None,
        "private_search_text": item.private_search_text,
        "display_name": item.display_name,
        "category": item.category,
        "price_kind": item.price_kind,
        "price_cents": item.price_cents,
        "relative_percent": item.relative_percent,
        "unit": item.unit,
        "service_date_local": item.service_date_local,
        "timing_kind": item.timing_kind,
        "timing_start_local": item.timing_start_local,
        "timing_end_local": item.timing_end_local,
        "timing_time_local": item.timing_time_local,
        "while_supplies_last": item.while_supplies_last,
        "source_post_key": item.source_post_key,
        "source_payload_hash": item.source_payload_hash,
    }


def create_missing_facts(
    inputs: dict[str, FactInput],
    *,
    release_name: str,
    families: dict[str, DealFamily],
) -> int:
    existing = existing_fact_keys(list(inputs))
    missing = [item for source_key, item in inputs.items() if source_key not in existing]
    if not missing:
        return 0

    candidates = [
        HistoricalDealFact(
            source_record_key=item.source_record_key,
            **fact_defaults(item, release_name=release_name, families=families),
        )
        for item in missing
    ]
    try:
        with transaction.atomic():
            HistoricalDealFact.objects.bulk_create(
                candidates,
                batch_size=BULK_CREATE_BATCH_SIZE,
            )
    except IntegrityError:
        created_count = 0
        for item in missing:
            _, created = HistoricalDealFact.objects.get_or_create(
                source_record_key=item.source_record_key,
                defaults=fact_defaults(item, release_name=release_name, families=families),
            )
            created_count += int(created)
        return created_count
    return len(candidates)


class Command(BaseCommand):
    help = "Import versioned historical deal facts for reproducible predictor analysis."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", default=str(DEFAULT_RELEASE / "manifest.json"))
        parser.add_argument("--dataset", default=str(DEFAULT_RELEASE / "historical-deals-v1.jsonl"))

    @transaction.atomic
    def handle(self, *args, **options):
        release, dataset = open_release(options["manifest"], options["dataset"])
        venues = {venue.slug: venue for venue in Venue.objects.all()}
        with import_run(release) as run:
            family_inputs: dict[str, FamilyInput] = {}
            fact_inputs: dict[str, FactInput] = {}
            for row in jsonl_rows(dataset):
                run.rows_seen += 1
                venue = venues.get(row["venue_slug"])
                if venue is None:
                    raise CommandError(f"Unknown venue {row['venue_slug']}; import venues first")
                family_id = row.get("canonical_family_source_id")
                if family_id:
                    family_inputs.setdefault(
                        family_id,
                        FamilyInput(
                            source_identifier=family_id,
                            canonical_name=row["canonical_family"],
                            category=row["category"],
                        ),
                    )
                source_key = row["source_record_key"]
                payload_hash = hashlib.sha256(
                    json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                display_name = public_deal_name(
                    row["display_name"],
                    price_kind=row["price_kind"],
                    price_cents=row.get("price_amount_cents"),
                    discount_percent=row.get("price_relative_percent"),
                )
                if not display_name:
                    raise CommandError(f"{source_key} has no product display name")
                fact_inputs.setdefault(
                    source_key,
                    FactInput(
                        source_record_key=source_key,
                        venue_id=venue.pk,
                        family_source_identifier=family_id,
                        private_search_text=normalize_deal_search_text(
                            row.get("raw_name") or ""
                        ),
                        display_name=display_name,
                        category=row["category"],
                        price_kind=row["price_kind"],
                        price_cents=row.get("price_amount_cents"),
                        relative_percent=row.get("price_relative_percent"),
                        unit=row.get("unit") or "",
                        service_date_local=row["service_date"],
                        timing_kind=row["timing_kind"],
                        timing_start_local=parse_time(row.get("timing_start_local")),
                        timing_end_local=parse_time(row.get("timing_end_local")),
                        timing_time_local=parse_time(row.get("timing_time_local")),
                        while_supplies_last=row["while_supplies_last"],
                        source_post_key=row["source_post_key"],
                        source_payload_hash=payload_hash,
                    ),
                )
            families = ensure_families(family_inputs)
            run.rows_accepted = create_missing_facts(
                fact_inputs,
                release_name=release.name,
                families=families,
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"{release.name}: {run.rows_seen} rows checked, {run.rows_accepted} facts created"
            )
        )
