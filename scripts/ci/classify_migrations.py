#!/usr/bin/env python3
"""Classify changed Django migrations without executing application code."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
from pathlib import Path

REVIEW_OPERATIONS = {
    "AddConstraint",
    "AlterField",
    "AlterIndexTogether",
    "AlterModelTable",
    "AlterUniqueTogether",
    "DeleteModel",
    "RemoveConstraint",
    "RemoveField",
    "RemoveIndex",
    "RenameField",
    "RenameIndex",
    "RenameModel",
    "RunPython",
    "RunSQL",
    "SeparateDatabaseAndState",
}

INITIALIZER_PATH = ".github/INITIALIZED"
INITIALIZER_CONTENT = (
    "IlliniCover v2 repository initialized. Source enters through a protected pull request.\n"
)
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")


class MigrationClassificationError(ValueError):
    pass


def risky_operations(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in REVIEW_OPERATIONS
    }
    return tuple(sorted(found))


def risky_paths(paths: list[Path]) -> list[tuple[Path, tuple[str, ...]]]:
    risky: list[tuple[Path, tuple[str, ...]]] = []
    for path in paths:
        if not path.is_file():
            risky.append((path, ("DeletedMigration",)))
            continue
        operations = risky_operations(path)
        if operations:
            risky.append((path, operations))
    return risky


def _git(repository: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise MigrationClassificationError(
            f"cannot inspect migration base with git {' '.join(arguments)}"
        ) from error
    return completed.stdout


def is_initial_source_import(repository: Path, base: str) -> bool:
    """Recognize only the one protected initializer tree with no application baseline."""

    if COMMIT_SHA.fullmatch(base) is None:
        raise MigrationClassificationError("migration base must be a full lowercase commit SHA")
    commit_and_parents = _git(repository, "rev-list", "--parents", "-n", "1", base).split()
    if commit_and_parents != [base]:
        return False
    files = tuple(
        line
        for line in _git(repository, "ls-tree", "-r", "--name-only", base).splitlines()
        if line
    )
    if files != (INITIALIZER_PATH,):
        return False
    marker = _git(repository, "show", f"{base}:{INITIALIZER_PATH}")
    return marker == INITIALIZER_CONTENT


def classify_changed_migrations(
    paths: list[Path],
    *,
    repository: Path | None = None,
    base: str | None = None,
) -> list[tuple[Path, tuple[str, ...]]]:
    if (repository is None) != (base is None):
        raise MigrationClassificationError("--repository and --base must be supplied together")
    if repository is not None and base is not None and is_initial_source_import(repository, base):
        return []
    return risky_paths(paths)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--base")
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()

    try:
        bootstrap_import = (
            args.repository is not None
            and args.base is not None
            and is_initial_source_import(args.repository, args.base)
        )
        risky = classify_changed_migrations(
            args.paths,
            repository=args.repository,
            base=args.base,
        )
    except MigrationClassificationError as error:
        parser.error(str(error))

    if not risky:
        if bootstrap_import:
            print(
                "migration risk: initial protected source import has no earlier schema; "
                "the fresh PostgreSQL migration job remains required"
            )
            return 0
        print("migration risk: no potentially incompatible operations in changed migrations")
        return 0
    for path, operations in risky:
        print(f"migration risk: {path}: {', '.join(operations)}")
    return 10


if __name__ == "__main__":
    raise SystemExit(main())
