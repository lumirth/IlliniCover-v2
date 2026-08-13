#!/usr/bin/env python3
"""Hash the exact file set that Cloud Build uploads for an IlliniCover release."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import struct
import subprocess
import sys
from fnmatch import fnmatchcase
from pathlib import Path

HASH_FORMAT_VERSION = b"illinicover-cloud-build-context-v1\0"
FORBIDDEN_LOCAL_ARTIFACT_PARTS = frozenset(
    {".artifacts", ".local", ".mypy_cache", ".pytest_cache", ".ruff_cache", "htmlcov"}
)


def validate_upload_paths(paths: list[str]) -> None:
    for relative in paths:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise RuntimeError(f"unsafe upload path reported by gcloud: {relative!r}")
        if (
            FORBIDDEN_LOCAL_ARTIFACT_PARTS.intersection(candidate.parts)
            or candidate.name == ".coverage"
            or fnmatchcase(candidate.name, "gha-creds-*.json")
        ):
            raise RuntimeError(f"forbidden local artifact in Cloud Build upload: {relative!r}")


def upload_paths(root: Path) -> list[str]:
    result = subprocess.run(
        [
            "gcloud",
            "meta",
            "list-files-for-upload",
            str(root),
            "--verbosity=error",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    paths = sorted(set(line for line in result.stdout.splitlines() if line))
    if not paths:
        raise RuntimeError("Cloud Build upload set is empty")
    validate_upload_paths(paths)
    return paths


def framed_digest(root: Path, paths: list[str]) -> str:
    validate_upload_paths(paths)
    digest = hashlib.sha256(HASH_FORMAT_VERSION)
    for relative in sorted(set(paths)):
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise RuntimeError(f"unsafe upload path reported by gcloud: {relative!r}")

        path = root / candidate
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISREG(metadata.st_mode):
            kind = b"file"
            payload = path.read_bytes()
        elif stat.S_ISLNK(metadata.st_mode):
            kind = b"symlink"
            payload = os.fsencode(os.readlink(path))
        else:
            raise RuntimeError(f"unsupported upload entry type: {relative!r}")

        encoded_path = os.fsencode(relative)
        digest.update(struct.pack(">Q", len(kind)))
        digest.update(kind)
        digest.update(struct.pack(">I", mode))
        digest.update(struct.pack(">Q", len(encoded_path)))
        digest.update(encoded_path)
        digest.update(struct.pack(">Q", len(payload)))
        digest.update(payload)
    return f"src-{digest.hexdigest()}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print a deterministic revision for the Cloud Build upload context."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root (defaults to the directory containing this script's project)",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        print(framed_digest(root, upload_paths(root)))
    except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"source revision failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
