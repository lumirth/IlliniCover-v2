#!/usr/bin/env python3
"""Minimal Neon preview branch cleanup helper; never prints credentials or URLs."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API_ROOT = "https://console.neon.tech/api/v2"


def request(method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    key = os.environ.get("NEON_API_KEY")
    if not key:
        raise ValueError("NEON_API_KEY is required")
    operation = urllib.request.Request(
        f"{API_ROOT}{path}",
        method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(operation, timeout=30) as response:
            if response.status == 204:
                return {}
            value = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Neon API returned HTTP {error.code}") from error
    if not isinstance(value, dict):
        raise ValueError("Neon API response was not an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    find = subparsers.add_parser("find")
    find.add_argument("--project", required=True)
    find.add_argument("--branch", required=True)
    delete = subparsers.add_parser("delete")
    delete.add_argument("--project", required=True)
    delete.add_argument("--branch-id", required=True)
    expire = subparsers.add_parser("expire")
    expire.add_argument("--project", required=True)
    expire.add_argument("--branch-id", required=True)
    expire.add_argument("--expires-at", required=True)
    args = parser.parse_args()

    if args.command == "find":
        response = request("GET", f"/projects/{args.project}/branches")
        branches = response.get("branches", [])
        if not isinstance(branches, list):
            raise ValueError("Neon branch list was malformed")
        matches = [
            branch.get("id")
            for branch in branches
            if isinstance(branch, dict) and branch.get("name") == args.branch
        ]
        if len(matches) > 1:
            raise ValueError("Neon returned duplicate branch names")
        if matches:
            print(matches[0])
    elif args.command == "delete":
        request("DELETE", f"/projects/{args.project}/branches/{args.branch_id}")
        print("Neon preview branch deleted", file=sys.stderr)
    else:
        response = request(
            "PATCH",
            f"/projects/{args.project}/branches/{args.branch_id}",
            {"branch": {"expires_at": args.expires_at}},
        )
        branch = response.get("branch", {})
        if not isinstance(branch, dict) or branch.get("expires_at") != args.expires_at:
            raise ValueError("Neon did not confirm the requested preview expiration")
        print("Neon preview expiration verified", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
