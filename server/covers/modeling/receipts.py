import hashlib
import json
from collections.abc import Mapping, Sequence

type JsonValue = None | bool | int | float | str | Sequence[JsonValue] | Mapping[str, JsonValue]


def canonical_receipt_bytes(value: JsonValue) -> bytes:
    """Encode a JSON-compatible receipt deterministically for hashing/storage."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def canonical_receipt_hash(value: JsonValue) -> str:
    return hashlib.sha256(canonical_receipt_bytes(value)).hexdigest()
