#!/usr/bin/env python3
"""Check the release identity that Cloud Run actually stored."""

import argparse
import json
import sys
from collections.abc import Iterator
from typing import Any


def containers(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        found = value.get("containers")
        if isinstance(found, list):
            yield from (item for item in found if isinstance(item, dict))
        for child in value.values():
            yield from containers(child)
    elif isinstance(value, list):
        for child in value:
            yield from containers(child)


parser = argparse.ArgumentParser()
parser.add_argument("--expected-image", required=True)
parser.add_argument("--expected-revision", required=True)
parser.add_argument("--expected-mode", choices=("direct", "pooled"), required=True)
parser.add_argument("--expected-secret", required=True)
args = parser.parse_args()
secret_name, secret_version = args.expected_secret.rsplit(":", 1)
if not secret_version.isdigit():
    parser.error("--expected-secret must end in a numeric provider version")

for container in containers(json.load(sys.stdin)):
    env = {item.get("name"): item for item in container.get("env", [])}
    reference = env.get("ILLINICOVER_SECRETS_JSON", {}).get("valueFrom", {}).get(
        "secretKeyRef", {}
    )
    valid = (
        container.get("image") == args.expected_image
        and env.get("CODE_REVISION", {}).get("value") == args.expected_revision
        and env.get("DATABASE_MODE", {}).get("value") == args.expected_mode
        and env.get("DEPLOYMENT_ENVIRONMENT", {}).get("value") == "production"
        and reference.get("name") == secret_name
        and reference.get("key") == secret_version
    )
    if valid:
        print("Cloud Run image, revision, mode, and secret reference verified")
        raise SystemExit(0)

raise SystemExit("Cloud Run readback does not match the intended release")
