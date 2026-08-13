#!/usr/bin/env python3
"""Project the small Cloud Run service state used by release and rollback."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def discover_service(resources: list[Any], name: str) -> str:
    matches = []
    for item in resources:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata", {})
        resource_name = metadata.get("name") if isinstance(metadata, dict) else None
        if resource_name == name:
            matches.append(item)
    if not matches:
        return "ABSENT"
    if len(matches) != 1:
        raise ValueError(f"expected at most one Cloud Run service named {name}")
    return "PRESENT"


def traffic(resource: dict[str, Any]) -> list[dict[str, Any]]:
    status = resource.get("status", {})
    values = status.get("traffic", []) if isinstance(status, dict) else []
    return [item for item in values if isinstance(item, dict)]


def serving_revision(resource: dict[str, Any]) -> str:
    serving = {
        item.get("revisionName")
        for item in traffic(resource)
        if isinstance(item.get("percent"), int)
        and item["percent"] > 0
        and isinstance(item.get("revisionName"), str)
    }
    if len(serving) != 1:
        raise ValueError("production traffic must resolve to exactly one untagged revision")
    revision = serving.pop()
    percent = sum(
        item.get("percent", 0)
        for item in traffic(resource)
        if item.get("revisionName") == revision and item.get("percent", 0) > 0
    )
    if percent != 100:
        raise ValueError("the serving revision must receive exactly 100 percent of traffic")
    if not isinstance(revision, str):
        raise ValueError("the serving revision name must be a string")
    return revision


def tagged_target(resource: dict[str, Any], tag: str) -> tuple[str, str]:
    matches = [item for item in traffic(resource) if item.get("tag") == tag]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one Cloud Run traffic tag named {tag}")
    revision = matches[0].get("revisionName")
    url = matches[0].get("url")
    if not isinstance(revision, str) or not revision:
        raise ValueError(f"Cloud Run tag {tag} has no revision")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ValueError(f"Cloud Run tag {tag} has no HTTPS URL")
    return revision, url


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--discover-name")
    group.add_argument("--serving-revision", action="store_true")
    group.add_argument("--tag-revision")
    group.add_argument("--tag-url")
    args = parser.parse_args()
    resource = json.load(sys.stdin)
    try:
        if args.discover_name:
            if not isinstance(resource, list):
                raise ValueError("Cloud Run service discovery requires a JSON list")
            value = discover_service(resource, args.discover_name)
        elif not isinstance(resource, dict):
            raise ValueError("Cloud Run service projection requires a JSON object")
        elif args.serving_revision:
            value = serving_revision(resource)
        elif args.tag_revision:
            value = tagged_target(resource, args.tag_revision)[0]
        else:
            value = tagged_target(resource, args.tag_url)[1]
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
