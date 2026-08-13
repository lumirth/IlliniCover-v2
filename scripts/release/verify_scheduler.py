#!/usr/bin/env python3
"""Discover or verify the nightly Cloud Scheduler release state."""

from __future__ import annotations

import argparse
import json
import sys

KNOWN_STATES = {"ENABLED", "PAUSED", "DISABLED", "UPDATE_FAILED"}


def discover_state(resources: object, name: str) -> str:
    if not isinstance(resources, list):
        raise ValueError("scheduler list response must be a JSON array")
    matches = [
        resource
        for resource in resources
        if isinstance(resource, dict)
        and str(resource.get("name", "")).rsplit("/", 1)[-1] == name
    ]
    if not matches:
        return "ABSENT"
    if len(matches) != 1:
        raise ValueError(f"expected at most one scheduler named {name}, got {len(matches)}")
    state = matches[0].get("state")
    if state not in KNOWN_STATES:
        raise ValueError(f"scheduler {name} reported invalid state {state!r}")
    return str(state)


def scheduler_projection(resource: object) -> dict[str, object]:
    if not isinstance(resource, dict):
        raise ValueError("scheduler resource must be a JSON object")
    target = resource.get("httpTarget", {})
    if not isinstance(target, dict):
        raise ValueError("scheduler httpTarget must be a JSON object")
    token = target.get("oauthToken", {})
    if not isinstance(token, dict):
        raise ValueError("scheduler oauthToken must be a JSON object")
    return {
        "schedule": resource.get("schedule"),
        "timeZone": resource.get("timeZone"),
        "uri": target.get("uri"),
        "httpMethod": target.get("httpMethod"),
        "serviceAccount": token.get("serviceAccountEmail"),
        "state": resource.get("state"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover-name")
    parser.add_argument("--schedule")
    parser.add_argument("--time-zone")
    parser.add_argument("--uri")
    parser.add_argument("--service-account")
    parser.add_argument("--state", choices=sorted(KNOWN_STATES))
    args = parser.parse_args()

    resource = json.load(sys.stdin)
    if args.discover_name:
        try:
            print(discover_state(resource, args.discover_name))
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 2
        return 0

    expected = {}
    for key, value in (
        ("schedule", args.schedule),
        ("timeZone", args.time_zone),
        ("uri", args.uri),
        ("serviceAccount", args.service_account),
        ("state", args.state),
    ):
        if value is not None:
            expected[key] = value
    if args.uri is not None or args.service_account is not None:
        expected["httpMethod"] = "POST"
    if not expected:
        parser.error("provide --discover-name or at least one expected scheduler field")

    try:
        projection = scheduler_projection(resource)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    actual = {key: projection[key] for key in expected}
    if actual != expected:
        print(f"nightly scheduler mismatch: expected {expected}, got {actual}", file=sys.stderr)
        return 2
    print(f"illinicover-nightly: {', '.join(expected)} verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
