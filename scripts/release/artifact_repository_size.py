#!/usr/bin/env python3
"""Print Artifact Registry's storage-cost size receipt for one repository."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()

    token = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not token:
        print("gcloud returned an empty access token", file=sys.stderr)
        return 2

    url = (
        "https://artifactregistry.googleapis.com/v1/"
        f"projects/{args.project}/locations/{args.location}/repositories/{args.repository}"
    )
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            repository = json.load(response)
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as error:
        print(f"Artifact Registry size lookup failed: {error}", file=sys.stderr)
        return 2

    size = repository.get("sizeBytes")
    if size is None:
        images = subprocess.run(
            [
                "gcloud",
                "artifacts",
                "docker",
                "images",
                "list",
                f"{args.location}-docker.pkg.dev/{args.project}/{args.repository}",
                "--format=value(version)",
                "--verbosity=error",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        if images:
            print("repository has images but the cost-size receipt is unavailable", file=sys.stderr)
            return 2
        size = "0"

    try:
        size_bytes = int(size)
    except (TypeError, ValueError):
        print(f"invalid Artifact Registry size receipt: {size!r}", file=sys.stderr)
        return 2
    if size_bytes < 0:
        print(f"invalid negative Artifact Registry size receipt: {size_bytes}", file=sys.stderr)
        return 2
    print(size_bytes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
