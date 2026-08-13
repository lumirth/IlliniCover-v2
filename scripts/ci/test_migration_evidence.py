from __future__ import annotations

import unittest

from migration_evidence import MigrationEvidenceError, restore_receipt, verify_release_evidence

HEAD = "a" * 40


def pull_request(*, merged: bool = True, label: bool = True, receipt: bool = True):
    return {
        "number": 42,
        "base": {"ref": "main"},
        "head": {"sha": HEAD},
        "merged_at": "2026-08-12T22:00:00Z" if merged else None,
        "labels": [{"name": "destructive-migration-reviewed"}] if label else [],
        "body": (
            "Destructive migration restore receipt: https://receipts.example/restore/42"
            if receipt
            else "No receipt"
        ),
    }


def preview_runs(*, sha: str = HEAD, conclusion: str = "success"):
    return {
        "workflow_runs": [
            {
                "event": "pull_request",
                "conclusion": conclusion,
                "head_sha": sha,
                "pull_requests": [{"number": 42}],
                "display_title": "Shared preview / labeled / 42",
                "run_number": 7,
                "html_url": "https://github.example/actions/runs/7",
            }
        ]
    }


class MigrationEvidenceTests(unittest.TestCase):
    def test_exact_pr_head_preview_and_restore_receipt_pass(self) -> None:
        result = verify_release_evidence(
            [pull_request()],
            preview_runs(),
            expected_head_sha=HEAD,
        )
        self.assertEqual(result["pr_number"], "42")
        self.assertEqual(result["pr_head_sha"], HEAD)

    def test_event_payload_may_verify_an_unmerged_pr_in_ci(self) -> None:
        result = verify_release_evidence(
            {"pull_request": pull_request(merged=False)},
            preview_runs(),
            expected_head_sha=HEAD,
            expected_pr_number=42,
            require_merged=False,
        )
        self.assertEqual(result["pr_number"], "42")

    def test_label_restore_receipt_and_exact_preview_are_all_required(self) -> None:
        cases = (
            ([pull_request(label=False)], preview_runs()),
            ([pull_request(receipt=False)], preview_runs()),
            ([pull_request()], preview_runs(sha="b" * 40)),
            ([pull_request()], preview_runs(conclusion="failure")),
        )
        for pulls, runs in cases:
            with self.subTest(pulls=pulls, runs=runs):
                with self.assertRaises(MigrationEvidenceError):
                    verify_release_evidence(pulls, runs, expected_head_sha=HEAD)

    def test_cleanup_run_does_not_count_as_a_deployed_preview(self) -> None:
        runs = preview_runs()
        runs["workflow_runs"][0]["display_title"] = "Shared preview / closed / 42"
        with self.assertRaises(MigrationEvidenceError):
            verify_release_evidence([pull_request()], runs, expected_head_sha=HEAD)

    def test_receipt_marker_requires_https(self) -> None:
        with self.assertRaises(MigrationEvidenceError):
            restore_receipt("Destructive migration restore receipt: http://unsafe.example")


if __name__ == "__main__":
    unittest.main()
