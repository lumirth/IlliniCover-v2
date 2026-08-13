import hashlib
import json
import uuid
from collections import defaultdict
from datetime import date
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from operations.models import DatasetRelease
from venues.models import Venue

from deals.models import (
    DealDefinition,
    DealPrediction,
    DealPredictionRelease,
    HistoricalDealFact,
)

PREDICTOR_VERSION = "deal_recurrence_v1"
SOURCE_DATASET = "historical-deals-v1"
RECEIPT_PATH = (
    Path(settings.REPOSITORY_DIR)
    / "data"
    / "deals"
    / "historical-deals-v1"
    / "model-selection-receipt.json"
)
DEFINITION_NAMESPACE = uuid.UUID("688ba1c2-2837-42ba-ae40-921e9e49184f")


class DealPredictionLifecycleError(ValueError):
    pass


def _receipt() -> dict:
    return json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))


def build_selected_prediction_release() -> DealPredictionRelease:
    """Create or retrieve the checked, receipt-backed initial release."""

    receipt = _receipt()
    training_revision = receipt["data"]["normalized_facts_sha256"]
    if not DatasetRelease.objects.filter(
        name=SOURCE_DATASET, content_hash=training_revision
    ).exists():
        raise RuntimeError("The checked deal training dataset release is not imported")
    release, _ = DealPredictionRelease.objects.get_or_create(
        predictor_version=PREDICTOR_VERSION,
        training_data_revision=training_revision,
        defaults={
            "code_revision": settings.CODE_REVISION,
            "parameters": receipt["model_release"]["prediction_contract"],
            "evaluation_metrics": receipt["model_release"]["selected_backtest"],
        },
    )
    return release


def _variant_key(fact: HistoricalDealFact) -> tuple:
    return (
        fact.display_name,
        fact.category,
        fact.price_kind,
        fact.price_cents,
        str(fact.relative_percent) if fact.relative_percent is not None else None,
        fact.unit,
        fact.timing_kind,
        fact.timing_start_local.isoformat() if fact.timing_start_local else None,
        fact.timing_end_local.isoformat() if fact.timing_end_local else None,
        fact.timing_time_local.isoformat() if fact.timing_time_local else None,
        fact.while_supplies_last,
    )


def _offer_identity_key(fact: HistoricalDealFact) -> tuple:
    """Match the selected model's family + serving + timing identity."""

    return (
        fact.family_id,
        fact.category,
        fact.unit,
        fact.timing_kind,
        fact.timing_start_local,
        fact.timing_end_local,
        fact.timing_time_local,
        fact.while_supplies_last,
    )


def _choose_variant(facts: list[HistoricalDealFact]) -> HistoricalDealFact:
    variants: dict[tuple, list[HistoricalDealFact]] = defaultdict(list)
    for fact in facts:
        variants[_variant_key(fact)].append(fact)
    ranked = sorted(
        variants.values(),
        key=lambda rows: (
            -len({row.service_date_local for row in rows}),
            -max(row.service_date_local.toordinal() for row in rows),
            min(row.source_record_key for row in rows),
        ),
    )
    return sorted(
        ranked[0], key=lambda row: (-row.service_date_local.toordinal(), row.source_record_key)
    )[0]


def _format_time(value) -> str:
    if value is None:
        return ""
    hour = value.hour % 12 or 12
    suffix = "AM" if value.hour < 12 else "PM"
    minute = f":{value.minute:02d}" if value.minute else ""
    return f"{hour}{minute} {suffix}"


def _timing(fact: HistoricalDealFact) -> tuple[str, bool]:
    if fact.timing_kind == "unknown":
        return "", False
    if fact.timing_kind == "all_night":
        return "All night", True
    if fact.timing_kind == "after_time":
        return f"After {_format_time(fact.timing_time_local)}", True
    if fact.timing_kind == "before_time":
        return f"Before {_format_time(fact.timing_time_local)}", True
    if fact.timing_kind == "between_times":
        return (
            f"{_format_time(fact.timing_start_local)}–{_format_time(fact.timing_end_local)}",
            True,
        )
    if fact.timing_kind == "until_sold_out":
        return "While supplies last", True
    return "", False


def _definition_for(fact: HistoricalDealFact) -> DealDefinition:
    variant = json.dumps(_variant_key(fact), separators=(",", ":"), default=str)
    identifier = uuid.uuid5(DEFINITION_NAMESPACE, f"{fact.venue_id}:{fact.family_id}:{variant}")
    timing_description, timing_known = _timing(fact)
    definition, _ = DealDefinition.objects.get_or_create(
        id=identifier,
        defaults={
            "venue": fact.venue,
            "family": fact.family,
            "display_name": fact.display_name,
            "category": fact.category,
            "price_kind": fact.price_kind,
            "price_cents": fact.price_cents,
            "discount_percent": fact.relative_percent,
            "unit": fact.unit,
            "serving_format": fact.unit,
            "timing_description": timing_description,
            "timing_known": timing_known,
            "while_supplies_last": fact.while_supplies_last,
            "status": "likely",
        },
    )
    return definition


@transaction.atomic
def promote_prediction_release(release: DealPredictionRelease) -> DealPredictionRelease:
    """Explicitly establish deal-predictor authority without rewriting history."""

    release = DealPredictionRelease.objects.select_for_update().get(pk=release.pk)
    if release.is_authoritative:
        return release
    if release.retired_at is not None:
        raise DealPredictionLifecycleError(
            "A retired deal prediction release cannot be promoted again"
        )

    now = timezone.now()
    current = (
        DealPredictionRelease.objects.select_for_update()
        .filter(is_authoritative=True)
        .first()
    )
    if current is not None:
        current.is_authoritative = False
        current.retired_at = now
        current.save(update_fields=["is_authoritative", "retired_at"])
    release.is_authoritative = True
    release.promoted_at = now
    release.save(update_fields=["is_authoritative", "promoted_at"])
    return release


@transaction.atomic
def materialize_predictions(service_date: date) -> tuple[DealPredictionRelease, int]:
    release = (
        DealPredictionRelease.objects.select_for_update()
        .filter(is_authoritative=True)
        .first()
    )
    if release is None:
        raise DealPredictionLifecycleError(
            "Deal predictions require a current authoritative release"
        )
    if release.retired_at is not None:
        raise DealPredictionLifecycleError(
            "The current deal prediction release cannot already be retired"
        )
    implementation = release.parameters.get("implementation", release.predictor_version)
    if implementation != PREDICTOR_VERSION:
        raise DealPredictionLifecycleError(
            f"No materializer is available for deal predictor {implementation!r}"
        )
    contract = release.parameters
    source_dataset = contract.get("source_dataset", SOURCE_DATASET)
    dataset_release = (
        DatasetRelease.objects.filter(
            name=source_dataset,
            content_hash=release.training_data_revision,
        )
        .order_by("created_at", "id")
        .first()
    )
    if dataset_release is None:
        raise RuntimeError("The authoritative deal release's training dataset is not imported")
    created = 0
    history_window = int(contract["history_window"])
    minimum_support = int(contract["minimum_night_support"])
    maximum_age = int(contract["maximum_history_age_days"])
    for venue in Venue.objects.filter(is_active=True):
        comparable_dates = list(
            HistoricalDealFact.objects.filter(
                venue=venue,
                source_dataset=dataset_release.name,
                service_date_local__lt=service_date,
                service_date_local__week_day=((service_date.weekday() + 1) % 7) + 1,
            )
            .order_by("-service_date_local")
            .values_list("service_date_local", flat=True)
            .distinct()[:history_window]
        )
        if not comparable_dates or (service_date - comparable_dates[0]).days > maximum_age:
            continue
        by_offer_identity: dict[tuple, list[HistoricalDealFact]] = defaultdict(list)
        facts = HistoricalDealFact.objects.filter(
            venue=venue,
            source_dataset=dataset_release.name,
            service_date_local__in=comparable_dates,
            family__isnull=False,
        ).select_related("family", "venue")
        for fact in facts:
            if fact.family_id is None:
                continue
            by_offer_identity[_offer_identity_key(fact)].append(fact)

        selected_offers: list[tuple[DealDefinition, int, date]] = []
        for identity_facts in by_offer_identity.values():
            supported_nights = {fact.service_date_local for fact in identity_facts}
            if len(supported_nights) < minimum_support:
                continue
            selected = _choose_variant(identity_facts)
            definition = _definition_for(selected)
            selected_offers.append((definition, len(supported_nights), max(supported_nights)))

        # Rank is part of the persisted predictor decision, not presentation
        # logic. The selected recurrence model already distinguishes offers by
        # comparable-night support and recency; the deterministic definition
        # UUID breaks the remaining tie without consulting client state.
        selected_offers.sort(
            key=lambda offer: (
                -offer[1],
                -offer[2].toordinal(),
                str(offer[0].id),
            )
        )
        for rank, (definition, support_nights, latest_evidence_date) in enumerate(
            selected_offers, start=1
        ):
            _, was_created = DealPrediction.objects.get_or_create(
                release=release,
                venue=venue,
                deal_definition=definition,
                service_date_local=service_date,
                defaults={
                    "support_nights": support_nights,
                    "comparable_nights": len(comparable_dates),
                    "latest_evidence_date": latest_evidence_date,
                    "rank": rank,
                    "status": "likely",
                },
            )
            created += int(was_created)
    return release, created


def prediction_receipt_hash() -> str:
    return hashlib.sha256(RECEIPT_PATH.read_bytes()).hexdigest()
