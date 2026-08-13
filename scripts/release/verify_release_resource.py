#!/usr/bin/env python3
"""Verify a Cloud Run JSON resource is pinned to one expected release."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from typing import Any


def containers(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        candidate = value.get("containers")
        if isinstance(candidate, list):
            yield from (item for item in candidate if isinstance(item, dict))
        for child in value.values():
            yield from containers(child)
    elif isinstance(value, list):
        for child in value:
            yield from containers(child)


def environment(container: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in container.get("env", []):
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            value = item.get("value")
            if isinstance(value, str):
                values[item["name"]] = value
    return values


def secret_environment(container: dict[str, Any]) -> dict[str, tuple[str, str]]:
    values: dict[str, tuple[str, str]] = {}
    for item in container.get("env", []):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        reference = item.get("valueFrom", {}).get("secretKeyRef", {})
        secret = reference.get("name")
        version = reference.get("key")
        if isinstance(secret, str) and isinstance(version, str):
            values[item["name"]] = (secret, version)
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--expected-image", required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument(
        "--expected-env",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Require an exact non-secret environment value; may be repeated.",
    )
    parser.add_argument(
        "--expected-secret",
        action="append",
        default=[],
        metavar="ENV=SECRET:VERSION",
        help="Require an exact numeric Secret Manager reference; may be repeated.",
    )
    args = parser.parse_args()

    expected_environment: dict[str, str] = {}
    for item in args.expected_env:
        if "=" not in item:
            parser.error("--expected-env must use NAME=VALUE")
        name, value = item.split("=", 1)
        if not name:
            parser.error("--expected-env requires a non-empty name")
        expected_environment[name] = value

    expected_secrets: dict[str, tuple[str, str]] = {}
    for item in args.expected_secret:
        if "=" not in item or ":" not in item:
            parser.error("--expected-secret must use ENV=SECRET:VERSION")
        name, reference = item.split("=", 1)
        secret, version = reference.rsplit(":", 1)
        if not name or not secret or not version.isdigit():
            parser.error("--expected-secret requires a numeric Secret Manager version")
        expected_secrets[name] = (secret, version)

    resource = json.load(sys.stdin)
    for container in containers(resource):
        if container.get("image") != args.expected_image:
            continue
        actual_environment = environment(container)
        actual_secrets = secret_environment(container)
        if actual_environment.get("CODE_REVISION") != args.expected_revision:
            continue
        if any(actual_environment.get(key) != value for key, value in expected_environment.items()):
            continue
        if any(actual_secrets.get(key) != value for key, value in expected_secrets.items()):
            continue
        print(
            f"{args.name}: image digest, code revision, environment, and secret versions verified"
        )
        return 0

    print(
        f"{args.name}: expected image digest or CODE_REVISION was not present",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
