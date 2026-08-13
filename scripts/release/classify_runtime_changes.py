#!/usr/bin/env python3
"""Decide whether one main advance changes production runtime inputs."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ZERO_SHA = "0" * 40
RUNTIME_FILES = {
    ".dockerignore",
    ".gcloudignore",
    ".github/workflows/deploy.yml",
    "docs/model/cover-historical-v1-evaluation.json",
    "docs/privacy-policy.md",
    "pyproject.toml",
    "scripts/ci/classify_migrations.py",
    "scripts/ci/migration_evidence.py",
    "uv.lock",
}
RUNTIME_PREFIXES = (
    ".github/actions/",
    "api/",
    "ops/cloudrun/",
    "ops/container/",
    "ops/deployment/",
    "server/",
)


@dataclass(frozen=True)
class RuntimeDecision:
    deploy: bool
    reason: str
    changed_paths: tuple[str, ...]
    runtime_paths: tuple[str, ...]


def _normalize(paths: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                path.strip().removeprefix("./")
                for path in paths
                if path.strip() and not PurePosixPath(path.strip()).is_absolute()
            }
        )
    )


def classify_paths(paths: Iterable[str]) -> RuntimeDecision:
    changed_paths = _normalize(paths)
    runtime_paths = tuple(path for path in changed_paths if _is_runtime_path(path))
    return RuntimeDecision(
        deploy=bool(runtime_paths),
        reason="runtime_changes" if runtime_paths else "no_runtime_changes",
        changed_paths=changed_paths,
        runtime_paths=runtime_paths,
    )


def _is_runtime_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if path.startswith("server/") and "tests" in parts[1:]:
        return False
    if path in RUNTIME_FILES or path.startswith(RUNTIME_PREFIXES):
        return True
    if path.startswith("data/"):
        return "source" not in parts and "cache" not in parts and parts[-1] != ".DS_Store"
    if path.startswith("scripts/release/"):
        return "__pycache__" not in parts and not parts[-1].startswith("test_")
    return False


def _all_files(repository: Path, revision: str) -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", revision],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(completed.stdout.splitlines())


def decide_repository_range(repository: Path, *, before: str, after: str) -> RuntimeDecision:
    if not _commit_exists(repository, after):
        return RuntimeDecision(True, "target_commit_unavailable", (), ())
    if before == ZERO_SHA:
        changed_paths = _all_files(repository, after)
        runtime_paths = tuple(path for path in changed_paths if _is_runtime_path(path))
        return RuntimeDecision(True, "initial_main_baseline", changed_paths, runtime_paths)
    if not _commit_exists(repository, before):
        return RuntimeDecision(True, "previous_commit_unavailable", (), ())
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", before, after],
        cwd=repository,
        check=False,
    ).returncode != 0:
        return RuntimeDecision(True, "previous_commit_not_ancestor", (), ())
    changed_paths = _changed_paths(repository, before=before, after=after)
    return classify_paths(changed_paths)


def _commit_exists(repository: Path, revision: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
            cwd=repository,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def _changed_paths(repository: Path, *, before: str, after: str) -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACDMRT", before, after],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(completed.stdout.splitlines())


def _append_summary(path: Path, decision: RuntimeDecision) -> None:
    title = "runtime release required" if decision.deploy else "no-op"
    with path.open("a", encoding="utf-8") as summary:
        summary.write(f"### Production deployment: {title}\n\n")
        summary.write(f"- Decision: `{decision.reason}`\n")
        summary.write(f"- Changed paths: {len(decision.changed_paths)}\n")
        summary.write(f"- Runtime paths: {len(decision.runtime_paths)}\n")
        if decision.deploy and decision.runtime_paths:
            summary.write("- Runtime inputs:\n")
            for changed_path in decision.runtime_paths:
                summary.write(f"  - `{changed_path}`\n")
        elif decision.deploy:
            summary.write(
                "\nHistory could not prove a safe no-op; the fail-safe release path will run.\n"
            )
        elif decision.changed_paths:
            summary.write("- Non-runtime paths:\n")
            for changed_path in decision.changed_paths:
                summary.write(f"  - `{changed_path}`\n")
            summary.write("\nNo GCP authentication, build, migration, or deploy will run.\n")


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    parser.add_argument("--github-summary", type=Path, required=True)
    args = parser.parse_args(arguments)
    decision = decide_repository_range(
        args.repository,
        before=args.before,
        after=args.after,
    )
    with args.github_output.open("a", encoding="utf-8") as output:
        output.write(f"deploy={'true' if decision.deploy else 'false'}\n")
        output.write(f"reason={decision.reason}\n")
        output.write(f"changed_count={len(decision.changed_paths)}\n")
        output.write(f"runtime_count={len(decision.runtime_paths)}\n")
    _append_summary(args.github_summary, decision)
    print(
        f"runtime deploy={'true' if decision.deploy else 'false'} "
        f"reason={decision.reason} changed={len(decision.changed_paths)} "
        f"runtime={len(decision.runtime_paths)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
