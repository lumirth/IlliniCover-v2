#!/usr/bin/env python3
"""Verify the request-log exclusion on the project's _Default sink."""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--filter", required=True)
    args = parser.parse_args()

    sink = json.load(sys.stdin)
    matches = [
        exclusion
        for exclusion in sink.get("exclusions", [])
        if exclusion.get("name") == args.name
    ]
    if len(matches) != 1:
        print(f"expected exactly one logging exclusion named {args.name}", file=sys.stderr)
        return 2
    exclusion = matches[0]
    if exclusion.get("filter") != args.filter or exclusion.get("disabled", False):
        print(
            f"logging exclusion is disabled or has the wrong filter: {exclusion}",
            file=sys.stderr,
        )
        return 2
    print(f"{args.name}: enabled request-log storage exclusion verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
