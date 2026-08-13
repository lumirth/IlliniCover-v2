#!/usr/bin/env python3
"""Build the deterministic recovered-cover-v1 release from its raw export."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

RELEASE_NAME = "recovered-cover-v1"
IMPORTER_VERSION = "cover_source_normalizer_v1"
SOURCE_ARTIFACT = "source/recovered_history.json"
OBSERVATIONS_ARTIFACT = "cover-observations-v1.jsonl"
REJECTIONS_ARTIFACT = "rejections-v1.jsonl"
RECEIPT_ARTIFACT = "normalization-receipt.json"
MANIFEST_ARTIFACT = "manifest.json"
SERVICE_TIME_ZONE = ZoneInfo("America/Chicago")
SERVICE_NIGHT_CUTOFF_HOUR = 5

SOURCE_VENUES = {
    "Brothers": "brothers",
    "Joe's": "joes",
    "Kam's": "kams",
    "Red Lion": "red-lion",
}


class RowError(ValueError):
    """A source row that can be preserved but cannot be admitted."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact(path: Path, *, rows: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "bytes": path.stat().st_size,
        "path": path.name if path.parent.name != "source" else f"source/{path.name}",
        "sha256": sha256(path),
    }
    if rows is not None:
        result["rows"] = rows
    return result


def write_json(path: Path, value: Any) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8")


def firestore_scalar(field: Any, *, field_name: str) -> tuple[str, Any]:
    if not isinstance(field, dict) or len(field) != 1:
        raise RowError(
            "malformed_firestore_field", f"{field_name} is not a one-value Firestore field"
        )
    firestore_type, raw_value = next(iter(field.items()))
    if firestore_type not in {"integerValue", "doubleValue"}:
        raise RowError("unsupported_firestore_type", f"{field_name} uses {firestore_type!r}")
    return firestore_type, raw_value


def decimal_value(raw_value: Any, *, field_name: str) -> Decimal:
    try:
        value = Decimal(str(raw_value))
    except (InvalidOperation, ValueError) as exc:
        raise RowError("invalid_number", f"{field_name} is not numeric") from exc
    if not value.is_finite():
        raise RowError("invalid_number", f"{field_name} is not finite")
    return value


def utc_iso_from_epoch(epoch_seconds: Decimal) -> str:
    # The original numeric value remains in source_timestamp. This rendering is
    # an import convenience, not a replacement for the source representation.
    timestamp = float(epoch_seconds)
    if not math.isfinite(timestamp):
        raise RowError("invalid_timestamp", "timestamp is not finite")
    try:
        value = datetime.fromtimestamp(timestamp, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise RowError(
            "invalid_timestamp", "timestamp is outside the supported datetime range"
        ) from exc
    return (
        value.isoformat(timespec="microseconds")
        .replace(".000000+00:00", "Z")
        .replace("+00:00", "Z")
    )


def service_date(epoch_seconds: Decimal) -> str:
    observed = datetime.fromtimestamp(float(epoch_seconds), tz=UTC).astimezone(SERVICE_TIME_ZONE)
    return (observed - timedelta(hours=SERVICE_NIGHT_CUTOFF_HOUR)).date().isoformat()


def normalize_row(source_venue: str, source_index: int, row: Any) -> dict[str, Any]:
    if source_venue not in SOURCE_VENUES:
        raise RowError("unknown_venue", f"unrecognized source collection {source_venue!r}")
    if not isinstance(row, dict):
        raise RowError("malformed_row", "row is not an object")

    source_key = row.get("name")
    fields = row.get("fields")
    if not isinstance(source_key, str) or not source_key:
        raise RowError("missing_source_key", "row has no Firestore document path")
    if not isinstance(fields, dict):
        raise RowError("missing_fields", "row has no Firestore fields object")

    price_type, raw_price = firestore_scalar(fields.get("cover"), field_name="cover")
    timestamp_type, raw_timestamp = firestore_scalar(
        fields.get("timestamp"), field_name="timestamp"
    )
    price_dollars = decimal_value(raw_price, field_name="cover")
    timestamp_seconds = decimal_value(raw_timestamp, field_name="timestamp")

    if price_dollars < 0:
        raise RowError("negative_cover_price", "cover price is below zero")
    price_cents_decimal = price_dollars * 100
    if price_cents_decimal != price_cents_decimal.to_integral_value():
        raise RowError("subcent_cover_price", "cover price cannot be represented as whole cents")
    if timestamp_seconds <= 0:
        raise RowError("invalid_timestamp", "timestamp must be positive")

    return {
        "firestore_create_time": row.get("createTime"),
        "firestore_update_time": row.get("updateTime"),
        "observed_at": utc_iso_from_epoch(timestamp_seconds),
        "observed_at_epoch_seconds": raw_timestamp,
        "price_currency": "USD",
        "reported_price_cents": int(price_cents_decimal),
        "reported_price_source_value": raw_price,
        "schema_version": 1,
        "service_date": service_date(timestamp_seconds),
        "service_night_cutoff": "05:00:00 America/Chicago",
        "source_collection": source_venue,
        "source_dataset": RELEASE_NAME,
        "source_index": source_index,
        "source_price_firestore_type": price_type,
        "source_record_key": source_key,
        "source_timestamp_firestore_type": timestamp_type,
        "venue_slug": SOURCE_VENUES[source_venue],
    }


def build_release(release_dir: Path, script_path: Path) -> dict[str, Any]:
    source_path = release_dir / SOURCE_ARTIFACT
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("source root must be an object keyed by venue collection")

    observations: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    rows_seen_by_venue: Counter[str] = Counter()
    accepted_by_venue: Counter[str] = Counter()
    source_keys: set[str] = set()

    for source_venue, rows in raw.items():
        if not isinstance(rows, list):
            raise ValueError(f"source collection {source_venue!r} must contain a list")
        for source_index, row in enumerate(rows):
            rows_seen_by_venue[source_venue] += 1
            source_key = row.get("name") if isinstance(row, dict) else None
            try:
                normalized = normalize_row(source_venue, source_index, row)
                if normalized["source_record_key"] in source_keys:
                    raise RowError("duplicate_source_key", "FireStore document path is duplicated")
                source_keys.add(normalized["source_record_key"])
                observations.append(normalized)
                accepted_by_venue[source_venue] += 1
            except RowError as exc:
                rejections.append(
                    {
                        "reason": exc.code,
                        "reason_detail": exc.detail,
                        "schema_version": 1,
                        "source_collection": source_venue,
                        "source_dataset": RELEASE_NAME,
                        "source_index": source_index,
                        "source_price": (
                            row.get("fields", {}).get("cover") if isinstance(row, dict) else None
                        ),
                        "source_record_key": source_key,
                        "source_timestamp": (
                            row.get("fields", {}).get("timestamp")
                            if isinstance(row, dict)
                            else None
                        ),
                    }
                )

    observations.sort(
        key=lambda row: (
            row["venue_slug"],
            Decimal(str(row["observed_at_epoch_seconds"])),
            row["source_record_key"],
        )
    )
    rejections.sort(key=lambda row: (str(row["source_collection"]), row["source_index"]))

    observations_path = release_dir / OBSERVATIONS_ARTIFACT
    rejections_path = release_dir / REJECTIONS_ARTIFACT
    receipt_path = release_dir / RECEIPT_ARTIFACT
    manifest_path = release_dir / MANIFEST_ARTIFACT
    write_jsonl(observations_path, observations)
    write_jsonl(rejections_path, rejections)

    price_counts = Counter(row["reported_price_cents"] for row in observations)
    receipt = {
        "acceptance_policy": {
            "accepted_price": "finite, non-negative, exactly representable in whole cents",
            "derived_service_date": "America/Chicago local observation time minus five hours",
            "identity": "exact source collection to venues-v1 slug mapping",
            "no_synthetic_fields": [
                "No user identity is invented.",
                "submitted_at is not synthesized from observed_at.",
                "Prices are not rounded to legacy UI increments.",
            ],
        },
        "dataset_release": RELEASE_NAME,
        "importer_version": IMPORTER_VERSION,
        "input_sha256": sha256(source_path),
        "price_cents_distribution": {
            str(key): value for key, value in sorted(price_counts.items())
        },
        "result": "succeeded_with_rejections" if rejections else "succeeded",
        "rows_accepted": len(observations),
        "rows_accepted_by_source_collection": dict(sorted(accepted_by_venue.items())),
        "rows_rejected": len(rejections),
        "rows_seen": sum(rows_seen_by_venue.values()),
        "rows_seen_by_source_collection": dict(sorted(rows_seen_by_venue.items())),
        "schema_version": 1,
        "unique_source_record_keys": len(source_keys),
    }
    write_json(receipt_path, receipt)

    manifest = {
        "artifacts": [
            artifact(source_path, rows=sum(rows_seen_by_venue.values())),
            artifact(observations_path, rows=len(observations)),
            artifact(rejections_path, rows=len(rejections)),
            artifact(receipt_path),
        ],
        "dataset_release": RELEASE_NAME,
        "importer": {
            "path": "scripts/data/build_cover_release.py",
            "sha256": sha256(script_path),
            "version": IMPORTER_VERSION,
        },
        "license_caveat": (
            "No standalone source-data license accompanied the v1 export. This release is for "
            "authorized internal migration and evaluation pending rights review; it is not a "
            "public redistribution grant."
        ),
        "manifest_schema_version": 1,
        "privacy_caveat": (
            "Firestore document paths are retained as pseudonymous provenance identifiers. Keep "
            "the raw and normalized release server-side and do not expose those keys through "
            "public APIs, telemetry, or client bundles."
        ),
        "provenance": {
            "chain": [
                "v1 Firestore document export",
                "byte-for-byte copy into recovered-cover-v1/source",
                "deterministic clean-room normalization by cover_source_normalizer_v1",
            ],
            "source_system": (
                "Firestore project icover-41a28, inferred from retained document paths"
            ),
            "source_timestamp_semantics": (
                "The export labels this numeric field timestamp; the original Firestore "
                "type/value, createTime, and updateTime are retained without claiming a stronger "
                "observation/submission distinction."
            ),
        },
        "release_date": "2026-08-12",
        "schema_version": 1,
    }
    write_json(manifest_path, manifest)
    return {"manifest": manifest, "receipt": receipt}


def parse_args() -> argparse.Namespace:
    repository_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-dir",
        type=Path,
        default=repository_root / "data/cover/recovered-cover-v1",
        help="release directory containing source/recovered_history.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_release(args.release_dir.resolve(), Path(__file__).resolve())
    print(canonical_json(result["receipt"]))


if __name__ == "__main__":
    main()
