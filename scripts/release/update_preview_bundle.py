#!/usr/bin/env python3
"""Replace one preview DB URL in a Secret Manager JSON bundle without printing it."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("pooled", "direct"), required=True)
    args = parser.parse_args()
    database_url = os.environ.get("PREVIEW_DATABASE_URL")
    if not database_url or not database_url.startswith(("postgres://", "postgresql://")):
        parser.error("PREVIEW_DATABASE_URL must be a PostgreSQL URL")
    bundle = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(bundle, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in bundle.items()
    ):
        raise ValueError("preview secret bundle must be a JSON object of strings")
    if not bundle.get("DJANGO_SECRET_KEY"):
        raise ValueError("preview bundle must already contain DJANGO_SECRET_KEY")
    if args.mode == "pooled":
        bundle["DATABASE_URL"] = database_url
        bundle.pop("DATABASE_URL_DIRECT", None)
    else:
        bundle["DATABASE_URL_DIRECT"] = database_url
        bundle.pop("DATABASE_URL", None)
    args.output.write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")
    args.output.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
