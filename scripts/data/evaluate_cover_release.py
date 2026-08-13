#!/usr/bin/env python3
"""Write a deterministic full historical model evaluation receipt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))

from covers.modeling.evaluation import release_evaluation  # noqa: E402
from covers.modeling.receipts import JsonValue, canonical_receipt_hash  # noqa: E402

DEFAULT_DATASET = Path("data/cover/recovered-cover-v1/cover-observations-v1.jsonl")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-revision", required=True)
    args = parser.parse_args()
    if not args.code_revision or args.code_revision == "development":
        parser.error("--code-revision must identify the evaluated source")

    evaluation = release_evaluation(args.dataset)
    payload = {
        "schema": "illinicover_model_evaluation_workflow_v1",
        "code_revision": args.code_revision,
        "evaluation_receipt_sha256": canonical_receipt_hash(cast(JsonValue, evaluation)),
        "evaluation": evaluation,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"historical evaluation {payload['evaluation_receipt_sha256']} "
        f"selected {evaluation['selected_release']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
