#!/usr/bin/env python3
"""Bound and safely retire billable Google Secret Manager versions.

This tool reads version metadata only.  It never accesses a secret payload.
Retirement is deliberately a separate, explicit command that disables and
read-backs each obsolete version before destroying it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Protocol

ACTIVE_STATES = frozenset({"ENABLED", "DISABLED"})


class SecretVersionError(ValueError):
    pass


@dataclass(frozen=True)
class SecretVersion:
    secret: str
    version: str
    state: str


class Cloud(Protocol):
    def secret_names(self, project: str) -> list[str]: ...

    def versions(self, project: str, secret: str) -> list[SecretVersion]: ...

    def disable(self, project: str, version: SecretVersion) -> None: ...

    def destroy(self, project: str, version: SecretVersion) -> None: ...

    def state(self, project: str, version: SecretVersion) -> str: ...


class GCloud:
    @staticmethod
    def _run(*arguments: str) -> str:
        completed = subprocess.run(
            ["gcloud", *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
        )
        return completed.stdout

    def secret_names(self, project: str) -> list[str]:
        output = self._run(
            "secrets",
            "list",
            "--project",
            project,
            "--format=value(name)",
        )
        return sorted({line.rsplit("/", 1)[-1] for line in output.splitlines() if line})

    def versions(self, project: str, secret: str) -> list[SecretVersion]:
        output = self._run(
            "secrets",
            "versions",
            "list",
            secret,
            "--project",
            project,
            "--format=json(name,state)",
        )
        payload: Any = json.loads(output)
        if not isinstance(payload, list):
            raise SecretVersionError(f"{secret}: expected a version metadata list")
        result: list[SecretVersion] = []
        for item in payload:
            if not isinstance(item, dict):
                raise SecretVersionError(f"{secret}: malformed version metadata")
            name = item.get("name")
            state = item.get("state")
            if not isinstance(name, str) or not isinstance(state, str):
                raise SecretVersionError(f"{secret}: incomplete version metadata")
            result.append(
                SecretVersion(secret=secret, version=name.rsplit("/", 1)[-1], state=state)
            )
        return result

    def disable(self, project: str, version: SecretVersion) -> None:
        self._run(
            "secrets",
            "versions",
            "disable",
            version.version,
            "--secret",
            version.secret,
            "--project",
            project,
            "--quiet",
        )

    def destroy(self, project: str, version: SecretVersion) -> None:
        self._run(
            "secrets",
            "versions",
            "destroy",
            version.version,
            "--secret",
            version.secret,
            "--project",
            project,
            "--quiet",
        )

    def state(self, project: str, version: SecretVersion) -> str:
        return self._run(
            "secrets",
            "versions",
            "describe",
            version.version,
            "--secret",
            version.secret,
            "--project",
            project,
            "--format=value(state)",
        ).strip()


def inventory(cloud: Cloud, project: str) -> list[SecretVersion]:
    return [
        version
        for secret in cloud.secret_names(project)
        for version in cloud.versions(project, secret)
    ]


def check_headroom(
    versions: list[SecretVersion],
    *,
    pending: int,
    settled_ceiling: int,
    rotation_ceiling: int,
    allow_candidates: bool = False,
    external_active: int = 0,
) -> tuple[int, int]:
    if pending < 0 or external_active < 0:
        raise SecretVersionError("pending and external active counts cannot be negative")
    active = [version for version in versions if version.state in ACTIVE_STATES]
    disabled = [version for version in active if version.state == "DISABLED"]
    if disabled:
        names = ", ".join(f"{item.secret}:{item.version}" for item in disabled)
        raise SecretVersionError(
            f"disabled versions are still billable and must be reconciled first: {names}"
        )
    current_ceiling = rotation_ceiling if allow_candidates else settled_ceiling
    active_total = len(active) + external_active
    if active_total > current_ceiling:
        raise SecretVersionError(
            f"active version inventory is {active_total}, above current ceiling {current_ceiling}"
        )
    projected = active_total + pending
    if projected > rotation_ceiling:
        raise SecretVersionError(
            f"operation would project {projected} active versions, above bounded rotation "
            f"ceiling {rotation_ceiling}"
        )
    counts: dict[str, int] = {}
    for item in active:
        counts[item.secret] = counts.get(item.secret, 0) + 1
    per_secret_ceiling = 2 if allow_candidates else 1
    duplicates = sorted(name for name, count in counts.items() if count > per_secret_ceiling)
    if duplicates:
        raise SecretVersionError(
            f"more than {per_secret_ceiling} active versions already exist for: "
            + ", ".join(duplicates)
        )
    return active_total, projected


def parse_keep(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SecretVersionError("--keep must use SECRET=VERSION")
        secret, version = value.split("=", 1)
        if not secret or not version.isdigit() or secret in result:
            raise SecretVersionError("--keep requires unique SECRET=numeric-version values")
        result[secret] = version
    if not result:
        raise SecretVersionError("at least one --keep value is required")
    return result


def retirement_plan(
    versions: list[SecretVersion], keep: dict[str, str]
) -> list[SecretVersion]:
    by_identity = {(item.secret, item.version): item for item in versions}
    for secret, version in keep.items():
        retained = by_identity.get((secret, version))
        if retained is None or retained.state != "ENABLED":
            raise SecretVersionError(f"retained version is not enabled: {secret}:{version}")
    return sorted(
        (
            item
            for item in versions
            if item.secret in keep
            and item.version != keep[item.secret]
            and item.state in ACTIVE_STATES
        ),
        key=lambda item: (item.secret, int(item.version)),
    )


def retire(
    cloud: Cloud,
    project: str,
    keep: dict[str, str],
    *,
    execute: bool,
) -> list[SecretVersion]:
    versions = [
        version
        for secret in keep
        for version in cloud.versions(project, secret)
    ]
    planned = retirement_plan(versions, keep)
    if not execute:
        return planned
    for item in planned:
        if item.state == "ENABLED":
            cloud.disable(project, item)
            if cloud.state(project, item) != "DISABLED":
                raise SecretVersionError(
                    f"refusing to destroy {item.secret}:{item.version}; disable readback failed"
                )
        cloud.destroy(project, item)
        if cloud.state(project, item) != "DESTROYED":
            raise SecretVersionError(
                f"destroy readback failed for {item.secret}:{item.version}"
            )
    return planned


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check")
    check.add_argument("--project", required=True)
    check.add_argument("--pending", required=True, type=int)
    check.add_argument("--settled-ceiling", type=int, default=6)
    check.add_argument("--rotation-ceiling", type=int, default=8)
    check.add_argument("--allow-candidates", action="store_true")
    check.add_argument(
        "--external-active",
        type=int,
        default=0,
        help="Receipt count for active versions in other billing-account projects.",
    )
    retire_parser = subparsers.add_parser("retire")
    retire_parser.add_argument("--project", required=True)
    retire_parser.add_argument("--keep", action="append", default=[])
    retire_parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    cloud = GCloud()
    try:
        if args.command == "check":
            active, projected = check_headroom(
                inventory(cloud, args.project),
                pending=args.pending,
                settled_ceiling=args.settled_ceiling,
                rotation_ceiling=args.rotation_ceiling,
                allow_candidates=args.allow_candidates,
                external_active=args.external_active,
            )
            print(
                f"Secret Manager inventory: {active} billable active versions; "
                f"bounded operation projection: {projected}."
            )
            return 0
        keep = parse_keep(args.keep)
        planned = retire(cloud, args.project, keep, execute=args.execute)
        action = "retired" if args.execute else "eligible"
        print(f"Secret Manager versions {action}: {len(planned)}")
        return 0
    except (SecretVersionError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
