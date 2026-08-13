#!/usr/bin/env python3
"""Verify the exceptional destructive-migration evidence for one exact PR head."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REVIEW_LABEL = "destructive-migration-reviewed"
RESTORE_RECEIPT = re.compile(
    r"(?im)^Destructive migration restore receipt:\s*(https://\S+)\s*$"
)


class MigrationEvidenceError(ValueError):
    pass


def restore_receipt(body: str | None) -> str:
    match = RESTORE_RECEIPT.search(body or "")
    if match is None:
        raise MigrationEvidenceError(
            "PR body must contain `Destructive migration restore receipt: https://...`"
        )
    receipt = match.group(1)
    parsed = urlparse(receipt)
    if parsed.scheme != "https" or not parsed.netloc:
        raise MigrationEvidenceError("destructive-migration restore receipt must be HTTPS")
    return receipt


def _pull_requests(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("pull_request"), dict):
        return [payload["pull_request"]]
    raise MigrationEvidenceError("GitHub did not return a pull request payload")


def verify_release_evidence(
    pulls_payload: Any,
    runs_payload: Any,
    *,
    expected_head_sha: str | None = None,
    expected_base: str = "main",
    expected_pr_number: int | None = None,
    require_merged: bool = True,
) -> dict[str, str]:
    candidates = []
    for pull in _pull_requests(pulls_payload):
        if pull.get("base", {}).get("ref") != expected_base:
            continue
        if expected_pr_number is not None and pull.get("number") != expected_pr_number:
            continue
        if expected_head_sha is not None and pull.get("head", {}).get("sha") != expected_head_sha:
            continue
        if require_merged and not pull.get("merged_at"):
            continue
        candidates.append(pull)
    if len(candidates) != 1:
        raise MigrationEvidenceError(
            "expected exactly one associated destructive-migration pull request"
        )

    pull = candidates[0]
    labels = {
        item.get("name")
        for item in pull.get("labels", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if REVIEW_LABEL not in labels:
        raise MigrationEvidenceError(f"pull request is missing the {REVIEW_LABEL} label")
    restore_url = restore_receipt(pull.get("body"))
    number = pull.get("number")
    if not isinstance(number, int):
        raise MigrationEvidenceError("pull request number is unavailable")
    head_sha = pull.get("head", {}).get("sha")
    if not isinstance(head_sha, str) or re.fullmatch(r"[0-9a-f]{40}", head_sha) is None:
        raise MigrationEvidenceError("pull request head SHA is unavailable or invalid")

    runs = runs_payload.get("workflow_runs", []) if isinstance(runs_payload, dict) else []
    if not isinstance(runs, list):
        raise MigrationEvidenceError("GitHub did not return preview workflow runs")
    matching_runs = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        run_prs = run.get("pull_requests", [])
        run_pr_numbers = {
            item.get("number")
            for item in run_prs
            if isinstance(item, dict) and isinstance(item.get("number"), int)
        }
        if (
            run.get("event") == "pull_request"
            and run.get("conclusion") == "success"
            and run.get("head_sha") == head_sha
            and number in run_pr_numbers
            and re.match(
                r"^Shared preview / (labeled|synchronize|reopened) / ",
                str(run.get("display_title", "")),
            )
        ):
            matching_runs.append(run)
    if not matching_runs:
        raise MigrationEvidenceError(
            "no successful shared-preview run is bound to this pull request and exact head SHA"
        )
    matching_runs.sort(key=lambda item: int(item.get("run_number", 0)), reverse=True)
    preview_url = matching_runs[0].get("html_url")
    parsed_preview = urlparse(preview_url or "")
    if parsed_preview.scheme != "https" or not parsed_preview.netloc:
        raise MigrationEvidenceError("successful preview run has no HTTPS receipt URL")
    return {
        "pr_number": str(number),
        "pr_head_sha": head_sha,
        "preview_receipt": str(preview_url),
        "restore_receipt": restore_url,
    }


def _write_github_values(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as output:
        for name, value in values.items():
            if "\n" in value or "\r" in value:
                raise MigrationEvidenceError(f"unsafe multiline GitHub output: {name}")
            output.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    receipt_parser = subparsers.add_parser("receipt")
    receipt_parser.add_argument("--body-env", default="DESTRUCTIVE_MIGRATION_PR_BODY")

    release_parser = subparsers.add_parser("release")
    release_parser.add_argument("--pulls", type=Path, required=True)
    release_parser.add_argument("--runs", type=Path, required=True)
    release_parser.add_argument("--expected-head-sha")
    release_parser.add_argument("--expected-pr-number", type=int)
    release_parser.add_argument("--allow-unmerged", action="store_true")
    release_parser.add_argument("--github-output", type=Path)
    release_parser.add_argument("--github-summary", type=Path)
    args = parser.parse_args()

    try:
        if args.command == "receipt":
            receipt = restore_receipt(os.environ.get(args.body_env))
            print(f"destructive migration restore receipt bound: {receipt}")
            return 0

        values = verify_release_evidence(
            json.loads(args.pulls.read_text(encoding="utf-8")),
            json.loads(args.runs.read_text(encoding="utf-8")),
            expected_head_sha=args.expected_head_sha,
            expected_pr_number=args.expected_pr_number,
            require_merged=not args.allow_unmerged,
        )
        if args.github_output:
            _write_github_values(args.github_output, values)
        if args.github_summary:
            with args.github_summary.open("a", encoding="utf-8") as summary:
                summary.write(
                    "### Destructive migration evidence\n\n"
                    f"- Pull request: #{values['pr_number']} at `{values['pr_head_sha']}`\n"
                    f"- Preview: {values['preview_receipt']}\n"
                    f"- Restore: {values['restore_receipt']}\n"
                )
        print(
            "destructive migration evidence verified for PR "
            f"#{values['pr_number']} at {values['pr_head_sha']}"
        )
        return 0
    except (MigrationEvidenceError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
