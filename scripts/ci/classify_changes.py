#!/usr/bin/env python3
"""Classify changed repository paths into independent CI seams."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path


def classify(paths: Iterable[str]) -> dict[str, bool]:
    normalized = {path.strip().removeprefix("./") for path in paths if path.strip()}

    def any_path(*prefixes: str) -> bool:
        return any(
            path == prefix or path.startswith(f"{prefix}/")
            for path in normalized
            for prefix in prefixes
        )

    backend = any_path("server") or bool(
        normalized & {"pyproject.toml", "uv.lock", "mise.toml"}
    )
    migrations = any("/migrations/" in f"/{path}" for path in normalized)
    contract = any_path("api/openapi.json") or any(
        path.startswith("server/")
        and (
            path.endswith("/api.py")
            or path.endswith("/schemas.py")
            or "export_client_openapi" in path
        )
        for path in normalized
    )
    non_fixture_server_seams = {
        "server/config",
    }
    fixture_config_producers = {
        "server/config/settings/base.py",
        "server/config/settings/fixtures.py",
    }
    fixtures = any_path("api/fixtures") or any(
        path.startswith("server/")
        and (
            path in fixture_config_producers
            or not any(
                path == prefix or path.startswith(f"{prefix}/")
                for prefix in non_fixture_server_seams
            )
        )
        and "/migrations/" not in f"/{path}"
        and not Path(path).name.startswith("test_")
        and (
            not path.startswith("server/operations/")
            or any(part in Path(path).name for part in ("seed", "scenario", "fixture", "export"))
        )
        for path in normalized
    )
    data = any_path("data", "tests/data") or any(
        path.startswith(("server/covers/", "server/deals/"))
        and any(part in path for part in ("model", "predict", "release", "import"))
        for path in normalized
    )
    ops = any_path("ops", ".github", "scripts/ci", "scripts/local", "scripts/release") or bool(
        normalized
        & {
            ".dockerignore",
            ".env.example",
            ".gcloudignore",
            "compose.yaml",
            "mise.toml",
            "renovate.json",
        }
    )
    ios = any_path("ios")
    return {
        "backend": backend,
        "migrations": migrations,
        "contract": contract,
        "fixtures": fixtures,
        "data": data,
        "ops": ops,
        "ios": ios,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    result = classify(sys.stdin)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            for name, enabled in result.items():
                output.write(f"{name}={'true' if enabled else 'false'}\n")
    else:
        json.dump(result, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
