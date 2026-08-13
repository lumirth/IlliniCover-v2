#!/usr/bin/env python3
"""Build historical-deals-v1 and evaluate deterministic recurrence models."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

DEAL_RELEASE = "historical-deals-v1"
IDENTITY_RELEASE = "deal-identities-v1"
ANALYZER_VERSION = "deal_recurrence_analysis_v1"
MODEL_NAME = "deal_recurrence_v1"
HOLDOUT_START = date(2024, 1, 1)

PLAN_SOURCE_NAME = "plan-v1-deterministic.jsonl"
REGISTRY_SOURCE_NAME = "deal_canonical_registry.jsonl"
NORMALIZED_NAME = "historical-deals-v1.jsonl"
REJECTIONS_NAME = "rejections-v1.jsonl"
RECEIPT_NAME = "model-selection-receipt.json"

EXPECTED_PLAN_SHA256 = "17933f02b1f4ece6b8f15428a0889eb8433d9384c0aa5d0e37b30490151c9691"
EXPECTED_REGISTRY_SHA256 = "7a1deac2f11bae5cb74f5145cd3d50d60c9b8e31d673d86253bb3c7b31376527"

VENUE_BY_HANDLE = {
    "brothersuofi": "brothers",
    "joesbrewery": "joes",
    "kams_illini": "kams",
    "redlionchampaign": "red-lion",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.write_text("".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def row_count(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def artifact(path: Path, relative_path: str, rows: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "bytes": path.stat().st_size,
        "path": relative_path,
        "sha256": sha256(path),
    }
    if rows is not None:
        result["rows"] = rows
    return result


def normalized_words(value: str | None) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    )
    return " ".join(re.findall(r"[a-z0-9]+", ascii_value.lower()))


def base_slug(value: str) -> str:
    return "_".join(normalized_words(value).split())[:64] or "unnamed"


def decimal_value(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} is not numeric: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"{field} is not finite")
    return result


def decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def stable_id(prefix: str, value: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class IdentityIndex:
    def __init__(self, registry_rows: list[dict[str, Any]]) -> None:
        self.rows = registry_rows
        self.by_id = {row["cluster_id"]: row for row in registry_rows}
        if len(self.by_id) != len(registry_rows):
            raise ValueError("canonical registry contains duplicate cluster_id values")

        self.root_by_cluster = {
            cluster_id: self._approved_root(cluster_id) for cluster_id in self.by_id
        }
        approved_drinks = [
            row
            for row in registry_rows
            if row["status"] == "approved" and row["entity_kind"] == "drink"
        ]
        slug_groups: dict[str, list[str]] = defaultdict(list)
        for row in approved_drinks:
            slug_groups[base_slug(row["canonical_name"])].append(row["cluster_id"])
        self.slug_by_root: dict[str, str] = {}
        for slug, cluster_ids in slug_groups.items():
            for cluster_id in cluster_ids:
                suffix = f"_{cluster_id}" if len(cluster_ids) > 1 else ""
                self.slug_by_root[cluster_id] = f"{slug}{suffix}"

        self.alias_targets: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.member_targets: dict[tuple[str, str], set[str]] = defaultdict(set)
        for row in registry_rows:
            root_id = self.root_by_cluster[row["cluster_id"]]
            if root_id is None:
                continue
            root = self.by_id[root_id]
            if root["entity_kind"] != row["entity_kind"]:
                # The reviewed registry contains a drink-labelled source cluster
                # merged into an event. Preserve that decision by excluding it
                # from drink aliases instead of coercing the approved root's kind.
                continue
            names = [row.get("representative"), row.get("canonical_name")]
            names.extend(member.get("raw_name") for member in row.get("members", []))
            for name in names:
                alias = normalized_words(name)
                if alias:
                    self.alias_targets[(row["entity_kind"], alias)].add(root_id)
            for member in row.get("members", []):
                alias = normalized_words(member.get("raw_name"))
                if not alias:
                    continue
                for post_key in member.get("post_keys", []):
                    self.member_targets[(post_key, alias)].add(root_id)

    def _approved_root(self, cluster_id: str) -> str | None:
        seen: set[str] = set()
        current = cluster_id
        while current:
            if current in seen:
                raise ValueError(f"merge cycle at cluster {cluster_id}")
            seen.add(current)
            row = self.by_id.get(current)
            if row is None:
                raise ValueError(f"missing merge target {current}")
            if row["status"] == "approved":
                return current
            if row["status"] == "merged":
                target = row.get("merged_into")
                if not isinstance(target, str) or not target:
                    raise ValueError(f"missing merge target for cluster {current}")
                current = target
                continue
            if row["status"] == "dropped":
                return None
            raise ValueError(f"unknown registry status {row['status']!r}")
        return None

    def resolve_drink(
        self, post_key: str, raw_name: str | None, canonical_name: str
    ) -> tuple[str | None, str]:
        raw_alias = normalized_words(raw_name)
        canonical_alias = normalized_words(canonical_name)
        member_roots = {
            root_id
            for root_id in self.member_targets.get((post_key, raw_alias), set())
            if self.by_id[root_id]["entity_kind"] == "drink"
        }
        exact_canonical = {
            root_id
            for root_id in member_roots
            if normalized_words(self.by_id[root_id]["canonical_name"]) == canonical_alias
        }
        if len(exact_canonical) == 1:
            return next(iter(exact_canonical)), "source_member_and_canonical"
        if len(member_roots) == 1:
            return next(iter(member_roots)), "source_member"
        if len(member_roots) > 1:
            return None, "ambiguous_source_membership"

        canonical_roots = self.alias_targets.get(("drink", canonical_alias), set())
        raw_roots = self.alias_targets.get(("drink", raw_alias), set())
        if len(canonical_roots) == 1:
            return next(iter(canonical_roots)), "canonical_alias"
        if len(raw_roots) == 1:
            return next(iter(raw_roots)), "raw_alias"
        if len(canonical_roots | raw_roots) > 1:
            return None, "ambiguous_alias"
        return None, "unresolved_identity"

    def stats(self) -> dict[str, Any]:
        status_counts = Counter(row["status"] for row in self.rows)
        kind_counts = Counter(row["entity_kind"] for row in self.rows)
        approved_kind_counts = Counter(
            row["entity_kind"] for row in self.rows if row["status"] == "approved"
        )
        ambiguous_drink_aliases = sorted(
            alias
            for (kind, alias), targets in self.alias_targets.items()
            if kind == "drink" and len(targets) > 1
        )
        return {
            "ambiguous_normalized_drink_alias_count": len(ambiguous_drink_aliases),
            "ambiguous_normalized_drink_aliases": ambiguous_drink_aliases,
            "approved_by_kind": dict(sorted(approved_kind_counts.items())),
            "clusters_by_kind": dict(sorted(kind_counts.items())),
            "clusters_by_status": dict(sorted(status_counts.items())),
            "clusters_total": len(self.rows),
            "historical_identity_slugs_are_collision_safe": True,
        }


def timing_fields(offer: dict[str, Any]) -> dict[str, Any]:
    span = offer.get("timing_span")
    cue = offer.get("availability_cue")
    start_time = offer.get("start_time")
    end_time = offer.get("end_time")
    while_supplies = cue == "while_supplies_last" or span == "while_supplies_last"
    if while_supplies:
        kind = "until_sold_out"
        time_value = start_value = end_value = None
    elif start_time and end_time:
        kind = "between_times"
        time_value, start_value, end_value = None, start_time, end_time
    elif start_time:
        kind = "after_time"
        time_value, start_value, end_value = start_time, None, None
    elif end_time:
        kind = "before_time"
        time_value, start_value, end_value = end_time, None, None
    elif span in {"all_night", "all_day", "until_close"}:
        kind = "all_night"
        time_value = start_value = end_value = None
    else:
        kind = "unknown"
        time_value = start_value = end_value = None
    return {
        "timing_end_local": end_value,
        "timing_kind": kind,
        "timing_start_local": start_value,
        "timing_time_local": time_value,
        "while_supplies_last": while_supplies,
    }


def service_date_fields(post: dict[str, Any], offer: dict[str, Any]) -> tuple[str, str]:
    if offer.get("start_date"):
        return offer["start_date"], "resolved_start_date"
    post_date = date.fromisoformat(post["post_date"])
    offset = int(offer.get("start_day_offset") or 0)
    if offset:
        return (post_date + timedelta(days=offset)).isoformat(), "offset_post_date"
    return post_date.isoformat(), "anchor_post_date"


def time_resolution(offer: dict[str, Any]) -> str:
    resolution = offer.get("temporal_resolution")
    if resolution == "explicit":
        return "resolved"
    if resolution == "inferred" and offer.get("recurrence"):
        return "recurring"
    if resolution == "inferred":
        return "ambiguous"
    return "fallback"


def normalized_price(pricing: dict[str, Any]) -> dict[str, Any]:
    price_type = pricing["price_type"]
    if price_type == "absolute":
        dollars = decimal_value(pricing.get("price_value"), "price_value")
        cents = dollars * 100
        if cents != cents.to_integral_value() or cents < 0:
            raise ValueError(f"invalid absolute price {dollars}")
        return {
            "price_amount_cents": int(cents),
            "price_kind": "single",
            "price_relative_percent": None,
        }
    if price_type == "relative":
        percent = decimal_value(pricing.get("relative_percent"), "relative_percent")
        return {
            "price_amount_cents": None,
            "price_kind": "relative",
            "price_relative_percent": decimal_text(percent),
        }
    raise ValueError(f"unsupported admitted price type {price_type!r}")


def normalize_fact(
    post: dict[str, Any],
    offer: dict[str, Any],
    pricing: dict[str, Any],
    offer_index: int,
    price_index: int,
    root_id: str,
    resolution_path: str,
    identities: IdentityIndex,
) -> dict[str, Any]:
    venue_slug = VENUE_BY_HANDLE[post["bar_handle"]]
    service_day, service_date_source = service_date_fields(post, offer)
    timing = timing_fields(offer)
    price = normalized_price(pricing)
    root = identities.by_id[root_id]
    source_key = f"plan-v1:{post['post_key']}:offer:{offer_index}:price:{price_index}"
    unit = offer.get("serving")
    offer_identity = {
        "canonical_family_source_id": root_id,
        "category": "drink",
        "serving_format": offer.get("serving"),
        "timing_end_local": timing["timing_end_local"],
        "timing_kind": timing["timing_kind"],
        "timing_start_local": timing["timing_start_local"],
        "timing_time_local": timing["timing_time_local"],
        "unit": unit,
        "while_supplies_last": timing["while_supplies_last"],
    }
    concrete_deal = {**offer_identity, **price}
    return {
        "canonical_family": identities.slug_by_root[root_id],
        "canonical_family_source_id": root_id,
        "category": "drink",
        "concrete_deal_id": stable_id("deal", concrete_deal),
        "display_name": root["canonical_name"],
        "name_type": root.get("name_type"),
        "offer_identity_id": stable_id("offer", offer_identity),
        "price_amount_cents": price["price_amount_cents"],
        "price_kind": price["price_kind"],
        "price_relative_percent": price["price_relative_percent"],
        "raw_canonical_name": offer.get("canonical_name"),
        "raw_name": offer.get("raw_name"),
        "schema_version": 1,
        "service_date": service_day,
        "service_date_source": service_date_source,
        "source_bar_handle": post["bar_handle"],
        "source_corpus_artifact_id": post.get("corpus_artifact_id"),
        "source_offer_index": offer_index,
        "source_output_schema_version": post.get("output", {}).get("schema_version"),
        "source_plan_name": post.get("plan_name"),
        "source_post_date": post["post_date"],
        "source_post_key": post["post_key"],
        "source_price_index": price_index,
        "source_record_key": source_key,
        "source_resolution": resolution_path,
        "source_temporal": {
            "availability_cue": offer.get("availability_cue"),
            "availability_first_n": offer.get("availability_first_n"),
            "end_date": offer.get("end_date"),
            "end_day_offset": offer.get("end_day_offset"),
            "end_time": offer.get("end_time"),
            "recurrence": offer.get("recurrence"),
            "start_date": offer.get("start_date"),
            "start_day_offset": offer.get("start_day_offset"),
            "start_time": offer.get("start_time"),
            "temporal_resolution": offer.get("temporal_resolution"),
            "timing_span": offer.get("timing_span"),
        },
        "time_resolution_status": time_resolution(offer),
        "timing_end_local": timing["timing_end_local"],
        "timing_kind": timing["timing_kind"],
        "timing_start_local": timing["timing_start_local"],
        "timing_time_local": timing["timing_time_local"],
        "unit": unit,
        "venue_slug": venue_slug,
        "while_supplies_last": timing["while_supplies_last"],
    }


def build_normalized_facts(
    plan_rows: list[dict[str, Any]], identities: IdentityIndex
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    source_offer_types: Counter[str] = Counter()
    source_price_types: Counter[str] = Counter()
    flow: Counter[str] = Counter()
    resolution_paths: Counter[str] = Counter()

    for post in plan_rows:
        if post["bar_handle"] not in VENUE_BY_HANDLE:
            raise ValueError(f"unknown bar handle {post['bar_handle']!r}")
        for offer_index, offer in enumerate(post["output"].get("offers", [])):
            offer_type = offer.get("offer_type")
            source_offer_types[str(offer_type)] += 1
            flow["source_offers"] += 1
            for pricing in offer.get("pricing") or []:
                source_price_types[str(pricing.get("price_type"))] += 1
            if offer_type != "drink":
                flow["skipped_non_drink_offers"] += 1
                continue
            flow["source_drink_offers"] += 1
            pricing_rows = offer.get("pricing") or []
            if not pricing_rows:
                flow["skipped_no_price"] += 1
                continue
            flow["priced_drink_offers"] += 1
            canonical_name = offer.get("canonical_name")
            if not canonical_name:
                flow["skipped_missing_canonical_name"] += 1
                continue
            flow["priced_named_drink_offers"] += 1
            for price_index, pricing in enumerate(pricing_rows):
                price_type = pricing.get("price_type")
                if price_type not in {"absolute", "relative"}:
                    flow[f"skipped_price_type_{price_type}"] += 1
                    continue
                flow["identity_resolution_attempts"] += 1
                root_id, resolution_path = identities.resolve_drink(
                    post["post_key"], offer.get("raw_name"), canonical_name
                )
                if root_id is None:
                    flow["rejected_identity"] += 1
                    rejections.append(
                        {
                            "canonical_name": canonical_name,
                            "offer_index": offer_index,
                            "price_index": price_index,
                            "raw_name": offer.get("raw_name"),
                            "reason": resolution_path,
                            "schema_version": 1,
                            "source_post_key": post["post_key"],
                            "source_record_key": (
                                f"plan-v1:{post['post_key']}:offer:{offer_index}:price:{price_index}"
                            ),
                        }
                    )
                    continue
                resolution_paths[resolution_path] += 1
                facts.append(
                    normalize_fact(
                        post,
                        offer,
                        pricing,
                        offer_index,
                        price_index,
                        root_id,
                        resolution_path,
                        identities,
                    )
                )
                flow["rows_accepted"] += 1

    facts.sort(
        key=lambda row: (
            row["venue_slug"],
            row["service_date"],
            row["source_record_key"],
        )
    )
    rejections.sort(key=lambda row: row["source_record_key"])
    if len({row["source_record_key"] for row in facts}) != len(facts):
        raise ValueError("accepted deal facts contain duplicate source_record_key values")
    flow["rows_rejected"] = len(rejections)
    return (
        facts,
        rejections,
        {
            "flow": dict(sorted(flow.items())),
            "identity_resolution_paths": dict(sorted(resolution_paths.items())),
            "source_offer_types": dict(sorted(source_offer_types.items())),
            "source_price_types": dict(sorted(source_price_types.items())),
        },
    )


def academic_phase(value: date) -> str:
    month_day = (value.month, value.day)
    if month_day >= (12, 15) or month_day <= (1, 15):
        return "winter_break"
    if month_day <= (5, 15):
        return "spring"
    if month_day <= (8, 15):
        return "summer"
    return "fall"


def group_nights(
    facts: list[dict[str, Any]],
) -> dict[str, dict[date, dict[str, set[str]]]]:
    nights: dict[str, dict[date, dict[str, set[str]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(set))
    )
    for row in facts:
        nights[row["venue_slug"]][date.fromisoformat(row["service_date"])][
            row["offer_identity_id"]
        ].add(row["concrete_deal_id"])
    return nights


def select_variants(
    history: list[tuple[date, dict[str, set[str]]]], minimum_support: int
) -> set[str]:
    identity_dates: dict[str, set[date]] = defaultdict(set)
    variant_dates: dict[tuple[str, str], set[date]] = defaultdict(set)
    for history_date, offers in history:
        for identity_id, variants in offers.items():
            identity_dates[identity_id].add(history_date)
            for variant in variants:
                variant_dates[(identity_id, variant)].add(history_date)

    selected: set[str] = set()
    for identity_id, dates in identity_dates.items():
        if len(dates) < minimum_support:
            continue
        candidates = [
            (len(seen_dates), max(seen_dates), variant)
            for (candidate_identity, variant), seen_dates in variant_dates.items()
            if candidate_identity == identity_id
        ]
        # Count first, then most-recent occurrence, then stable identifier.
        selected.add(max(candidates)[2])
    return selected


def evaluate_candidate(
    nights: dict[str, dict[date, dict[str, set[str]]]],
    *,
    window: int,
    minimum_support: int,
    max_age_days: int | None,
    same_phase: bool = False,
) -> dict[str, Any]:
    true_positive = false_positive = false_negative = 0
    target_nights = empty_predictions = exact_nights = 0
    per_venue: dict[str, Counter[str]] = defaultdict(Counter)

    for venue, venue_nights in sorted(nights.items()):
        ordered_dates = sorted(venue_nights)
        for target_date in ordered_dates:
            if target_date < HOLDOUT_START:
                continue
            actual = {
                concrete for variants in venue_nights[target_date].values() for concrete in variants
            }
            history_dates = [
                candidate_date
                for candidate_date in ordered_dates
                if candidate_date < target_date
                and candidate_date.weekday() == target_date.weekday()
                and (
                    not same_phase or academic_phase(candidate_date) == academic_phase(target_date)
                )
            ]
            history_dates = history_dates[-window:]
            history = [
                (candidate_date, venue_nights[candidate_date]) for candidate_date in history_dates
            ]
            if (
                history
                and max_age_days is not None
                and (target_date - history[-1][0]).days > max_age_days
            ):
                history = []
            predicted = select_variants(history, minimum_support) if history else set()

            tp = len(predicted & actual)
            fp = len(predicted - actual)
            fn = len(actual - predicted)
            true_positive += tp
            false_positive += fp
            false_negative += fn
            target_nights += 1
            empty_predictions += not predicted
            exact_nights += predicted == actual
            per_venue[venue].update(
                {
                    "empty_predictions": int(not predicted),
                    "false_negative": fn,
                    "false_positive": fp,
                    "target_nights": 1,
                    "true_positive": tp,
                }
            )

    precision = true_positive / (true_positive + false_positive)
    recall = true_positive / (true_positive + false_negative)
    f1 = 2 * precision * recall / (precision + recall)
    beta_squared = Decimal("0.25")
    f_half = float(
        (1 + beta_squared)
        * Decimal(str(precision))
        * Decimal(str(recall))
        / (beta_squared * Decimal(str(precision)) + Decimal(str(recall)))
    )
    return {
        "empty_prediction_rate": round(empty_predictions / target_nights, 6),
        "exact_night_rate": round(exact_nights / target_nights, 6),
        "f0_5": round(f_half, 6),
        "f1": round(f1, 6),
        "false_negative": false_negative,
        "false_positive": false_positive,
        "per_venue": {
            venue: dict(sorted(values.items())) for venue, values in sorted(per_venue.items())
        },
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "target_nights": target_nights,
        "true_positive": true_positive,
    }


def support_bins(values: Iterable[int]) -> dict[str, int]:
    bins: Counter[str] = Counter()
    for value in values:
        if value == 1:
            bins["1"] += 1
        elif value == 2:
            bins["2"] += 1
        elif value == 3:
            bins["3"] += 1
        elif value <= 7:
            bins["4_to_7"] += 1
        elif value <= 15:
            bins["8_to_15"] += 1
        else:
            bins["16_plus"] += 1
    return dict(sorted(bins.items()))


def stability_summary(
    facts: list[dict[str, Any]],
    group_fields: tuple[str, ...],
    variant_fields: tuple[str, ...],
) -> dict[str, Any]:
    groups: dict[tuple[Any, ...], dict[tuple[Any, ...], set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for row in facts:
        group = tuple(row[field] for field in group_fields)
        variant = tuple(row[field] for field in variant_fields)
        groups[group][variant].add(row["service_date"])
    eligible = []
    for variants in groups.values():
        all_dates = set().union(*variants.values())
        if len(all_dates) >= 4:
            appearances = sum(len(dates) for dates in variants.values())
            modal_share = max(len(dates) for dates in variants.values()) / appearances
            eligible.append((len(variants), modal_share))
    return {
        "groups_support_at_least_4": len(eligible),
        "groups_with_multiple_variants": sum(count > 1 for count, _ in eligible),
        "modal_share_at_least_0_75": sum(share >= 0.75 for _, share in eligible),
        "modal_share_at_least_0_90": sum(share >= 0.90 for _, share in eligible),
    }


def descriptive_analysis(facts: list[dict[str, Any]], identities: IdentityIndex) -> dict[str, Any]:
    venue_rows = Counter(row["venue_slug"] for row in facts)
    venue_nights: dict[str, set[str]] = defaultdict(set)
    venue_families: dict[str, set[str]] = defaultdict(set)
    family_nights: dict[tuple[str, str], set[str]] = defaultdict(set)
    timing_counts = Counter(row["timing_kind"] for row in facts)
    resolution_counts = Counter(row["time_resolution_status"] for row in facts)
    price_counts = Counter(row["price_kind"] for row in facts)
    phase_rows: Counter[str] = Counter()
    phase_nights: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in facts:
        venue = row["venue_slug"]
        service_day = row["service_date"]
        family = row["canonical_family_source_id"]
        venue_nights[venue].add(service_day)
        venue_families[venue].add(family)
        family_nights[(venue, family)].add(service_day)
        phase = academic_phase(date.fromisoformat(service_day))
        phase_rows[phase] += 1
        phase_nights[(venue, phase)].add(service_day)

    price_group_fields = (
        "venue_slug",
        "canonical_family_source_id",
        "unit",
        "timing_kind",
        "timing_time_local",
        "timing_start_local",
        "timing_end_local",
        "while_supplies_last",
    )
    timing_group_fields = (
        "venue_slug",
        "canonical_family_source_id",
        "unit",
        "price_kind",
        "price_amount_cents",
        "price_relative_percent",
        "while_supplies_last",
    )
    return {
        "confirmation_and_denial_behavior": {
            "structured_confirmations": 0,
            "structured_corrections": 0,
            "structured_denials": 0,
            "conclusion": (
                "The source release cannot estimate evidence-action effects; same-night actions "
                "must be a deterministic overlay and evaluated prospectively."
            ),
        },
        "date_range": {
            "maximum": max(row["service_date"] for row in facts),
            "minimum": min(row["service_date"] for row in facts),
        },
        "distinct_concrete_deals": len({row["concrete_deal_id"] for row in facts}),
        "distinct_offer_identities": len({row["offer_identity_id"] for row in facts}),
        "evidence_sparsity": {
            "venue_family_groups": len(family_nights),
            "venue_family_night_support_bins": support_bins(len(v) for v in family_nights.values()),
        },
        "identity": {
            **identities.stats(),
            "approved_drink_families_used": len(
                {row["canonical_family_source_id"] for row in facts}
            ),
        },
        "price_kind_rows": dict(sorted(price_counts.items())),
        "price_stability": stability_summary(
            facts,
            price_group_fields,
            ("price_kind", "price_amount_cents", "price_relative_percent"),
        ),
        "rows": len(facts),
        "seasonality": {
            "phase_definition": (
                "winter break Dec 15-Jan 15; spring through May 15; summer through Aug 15; "
                "fall through Dec 14. This is a diagnostic approximation, not authoritative "
                "academic-calendar context."
            ),
            "rows_by_phase": dict(sorted(phase_rows.items())),
            "venue_nights_by_phase": {
                f"{venue}:{phase}": len(days)
                for (venue, phase), days in sorted(phase_nights.items())
            },
        },
        "time_resolution_rows": dict(sorted(resolution_counts.items())),
        "timing_kind_rows": dict(sorted(timing_counts.items())),
        "timing_stability": stability_summary(
            facts,
            timing_group_fields,
            (
                "timing_kind",
                "timing_time_local",
                "timing_start_local",
                "timing_end_local",
            ),
        ),
        "venue_level": {
            venue: {
                "families": len(venue_families[venue]),
                "nights": len(venue_nights[venue]),
                "rows": venue_rows[venue],
            }
            for venue in sorted(venue_rows)
        },
    }


def model_receipt(
    facts: list[dict[str, Any]],
    identities: IdentityIndex,
    import_stats: dict[str, Any],
    plan_path: Path,
    registry_path: Path,
    normalized_path: Path,
    analyzer_path: Path,
) -> dict[str, Any]:
    nights = group_nights(facts)
    candidates = {
        "last_same_weekday": evaluate_candidate(
            nights, window=1, minimum_support=1, max_age_days=None
        ),
        "two_of_last_four": evaluate_candidate(
            nights, window=4, minimum_support=2, max_age_days=None
        ),
        "two_of_last_three": evaluate_candidate(
            nights, window=3, minimum_support=2, max_age_days=None
        ),
        "two_of_last_three_90d": evaluate_candidate(
            nights, window=3, minimum_support=2, max_age_days=90
        ),
        "two_of_last_three_same_phase": evaluate_candidate(
            nights,
            window=3,
            minimum_support=2,
            max_age_days=90,
            same_phase=True,
        ),
        "three_of_last_four": evaluate_candidate(
            nights, window=4, minimum_support=3, max_age_days=None
        ),
    }
    selected = candidates["two_of_last_three_90d"]
    return {
        "analysis_version": ANALYZER_VERSION,
        "backtest": {
            "candidates": candidates,
            "holdout_start": HOLDOUT_START.isoformat(),
            "label_definition": (
                "For each venue/service-date present in the source release, the target is the "
                "set union of imported concrete drink offers advertised for that date."
            ),
            "leakage_control": (
                "Each target uses only strictly earlier service dates for the same venue; model "
                "selection is an expanding-window chronological backtest."
            ),
            "metric_aggregation": "Micro-averaged exact concrete-deal set membership.",
            "selection_rule": (
                "Require micro recall >= 0.40, then maximize precision. Prefer a bounded stale "
                "history and an empty slate over resurrecting old offers."
            ),
            "target_scope_caveat": (
                "Nights with no source post are absent, not verified empty slates. Within a "
                "source-post night, omission is used as a backtest negative but is not proof that "
                "the venue did not run the offer."
            ),
        },
        "data": {
            "canonical_registry_sha256": sha256(registry_path),
            "historical_plan_sha256": sha256(plan_path),
            "normalized_facts_sha256": sha256(normalized_path),
            "normalization": import_stats,
        },
        "descriptive_analysis": descriptive_analysis(facts, identities),
        "limitations": [
            "Labels are extracted advertisements, not verified point-of-sale truth.",
            "The source has no explicit empty-night sampling frame.",
            "There are no structured confirmation, denial, or correction outcomes.",
            "Timing marked unknown remains unknown and is never rewritten as all night.",
            "The simple academic phase is diagnostic only; live context must come from a "
            "versioned, as-of source.",
            "Performance is an initial historical estimate and requires prospective calibration.",
        ],
        "model_release": {
            "action_overlay": {
                "ADD_MISSING": "Add a same-night candidate with evidence lineage.",
                "CONFIRM_PRESENT": "Retain and mark the concrete candidate confirmed.",
                "CORRECT": "Supersede for the service night while preserving prior lineage.",
                "DENY_PRESENT": "Suppress for the service night without deleting history.",
            },
            "confidence": "initial_low",
            "name": MODEL_NAME,
            "prediction_contract": {
                "allow_empty_slate": True,
                "comparable_history": "same venue and weekday",
                "history_window": 3,
                "maximum_history_age_days": 90,
                "minimum_night_support": 2,
                "unknown_timing_policy": "preserve_unknown",
                "variant_choice": (
                    "Highest distinct-night count, then most recent occurrence, then stable ID."
                ),
            },
            "selected_backtest": selected,
            "selected_candidate": "two_of_last_three_90d",
            "selection_reason": (
                "It has the highest precision among tested candidates meeting the 0.40 recall "
                "floor, while the 90-day cap prevents indefinite resurrection of stale deals."
            ),
        },
        "receipt_schema_version": 1,
        "reproducibility": {
            "analyzer_path": "scripts/data/analyze_deal_recurrence.py",
            "analyzer_sha256": sha256(analyzer_path),
            "command": "python3 scripts/data/analyze_deal_recurrence.py",
            "external_services_used": [],
            "paid_resources_used": False,
        },
    }


def build_release(
    deal_dir: Path,
    identity_dir: Path,
    analyzer_path: Path,
    *,
    require_pinned_sources: bool = True,
) -> dict[str, Any]:
    plan_path = deal_dir / "source" / PLAN_SOURCE_NAME
    registry_path = identity_dir / "source" / REGISTRY_SOURCE_NAME
    if require_pinned_sources:
        if sha256(plan_path) != EXPECTED_PLAN_SHA256:
            raise ValueError("historical plan does not match the historical-deals-v1 source hash")
        if sha256(registry_path) != EXPECTED_REGISTRY_SHA256:
            raise ValueError("canonical registry does not match the deal-identities-v1 source hash")

    plan_rows = load_jsonl(plan_path)
    registry_rows = load_jsonl(registry_path)
    identities = IdentityIndex(registry_rows)
    facts, rejections, import_stats = build_normalized_facts(plan_rows, identities)
    if len(facts) != 13_786 or len(rejections) != 72:
        raise ValueError(
            f"unexpected release counts: {len(facts)} accepted, {len(rejections)} rejected"
        )

    normalized_path = deal_dir / NORMALIZED_NAME
    rejections_path = deal_dir / REJECTIONS_NAME
    receipt_path = deal_dir / RECEIPT_NAME
    write_jsonl(normalized_path, facts)
    write_jsonl(rejections_path, rejections)
    receipt = model_receipt(
        facts,
        identities,
        import_stats,
        plan_path,
        registry_path,
        normalized_path,
        analyzer_path,
    )
    write_json(receipt_path, receipt)

    identity_manifest = {
        "artifacts": [
            artifact(
                registry_path,
                f"source/{REGISTRY_SOURCE_NAME}",
                rows=len(registry_rows),
            )
        ],
        "dataset_release": IDENTITY_RELEASE,
        "license_caveat": (
            "No standalone license accompanied the source registry. This is an authorized "
            "internal migration/evaluation artifact, not a public redistribution grant."
        ),
        "manifest_schema_version": 1,
        "privacy_caveat": (
            "Registry examples retain Instagram post keys and handles as provenance. Keep the "
            "raw registry server-side and out of public APIs, telemetry, and client bundles."
        ),
        "provenance": {
            "review_state": "The source explicitly records approved, merged, and dropped clusters.",
            "source": "Reviewed canonical registry derived from historical Instagram extraction.",
            "stats": identities.stats(),
        },
        "release_date": "2026-08-12",
        "schema_version": 1,
    }
    write_json(identity_dir / "manifest.json", identity_manifest)

    historical_manifest = {
        "artifacts": [
            artifact(plan_path, f"source/{PLAN_SOURCE_NAME}", rows=len(plan_rows)),
            artifact(normalized_path, NORMALIZED_NAME, rows=len(facts)),
            artifact(rejections_path, REJECTIONS_NAME, rows=len(rejections)),
            artifact(receipt_path, RECEIPT_NAME),
        ],
        "dataset_release": DEAL_RELEASE,
        "identity_release": {
            "dataset_release": IDENTITY_RELEASE,
            "source_sha256": sha256(registry_path),
        },
        "license_caveat": (
            "The source is a historical Instagram extraction. No license for captions, media, "
            "or public redistribution accompanied it. Use is limited to authorized internal "
            "migration/evaluation pending rights review."
        ),
        "manifest_schema_version": 1,
        "normalizer": {
            "path": "scripts/data/analyze_deal_recurrence.py",
            "sha256": sha256(analyzer_path),
            "version": ANALYZER_VERSION,
        },
        "privacy_caveat": (
            "Post keys, handles, and extracted offer text are retained for provenance and may be "
            "pseudonymous. Do not expose raw source fields through public APIs or client bundles."
        ),
        "provenance": {
            "chain": [
                "historical Instagram posts",
                "deterministic structured extraction plan",
                "byte-for-byte copy into historical-deals-v1/source",
                "clean-room exact canonical-registry resolution and normalization",
            ],
            "nonportable_metadata": (
                "Each raw row contains a historical local plan_path. The v2 normalizer ignores "
                "that path; plan_name and content hashes are the portable provenance fields."
            ),
        },
        "release_date": "2026-08-12",
        "schema_version": 1,
    }
    write_json(deal_dir / "manifest.json", historical_manifest)
    return {
        "facts": facts,
        "historical_manifest": historical_manifest,
        "identity_manifest": identity_manifest,
        "receipt": receipt,
        "rejections": rejections,
    }


def parse_args() -> argparse.Namespace:
    repository_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--deal-dir",
        type=Path,
        default=repository_root / "data/deals/historical-deals-v1",
    )
    parser.add_argument(
        "--identity-dir",
        type=Path,
        default=repository_root / "data/deals/deal-identities-v1",
    )
    parser.add_argument(
        "--allow-unpinned-sources",
        action="store_true",
        help="permit analysis fixtures whose hashes differ from the release-v1 source pins",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_release(
        args.deal_dir.resolve(),
        args.identity_dir.resolve(),
        Path(__file__).resolve(),
        require_pinned_sources=not args.allow_unpinned_sources,
    )
    print(canonical_json(result["receipt"]["model_release"]))


if __name__ == "__main__":
    main()
