from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from classify_runtime_changes import (
    ZERO_SHA,
    RuntimeDecision,
    classify_paths,
    decide_repository_range,
    main,
)


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


class GitRepository:
    def __init__(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name)
        _git(self.path, "init", "--initial-branch=main")
        _git(self.path, "config", "user.name", "Runtime classifier test")
        _git(self.path, "config", "user.email", "runtime-classifier@example.test")

    def commit(self, path: str, content: str, message: str) -> str:
        target = self.path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        _git(self.path, "add", "--all")
        _git(self.path, "commit", "--message", message)
        return _git(self.path, "rev-parse", "HEAD")

    def close(self) -> None:
        self.temporary_directory.cleanup()


class RuntimePathClassificationTests(unittest.TestCase):
    def test_ios_and_non_runtime_docs_are_recorded_as_noop(self) -> None:
        decision = classify_paths(
            [
                "ios/IlliniCover/Features/Cover/CoverView.swift",
                "docs/runbooks/deployment.md",
                "docs/product/specification.md",
            ]
        )

        self.assertFalse(decision.deploy)
        self.assertEqual(decision.reason, "no_runtime_changes")
        self.assertEqual(decision.runtime_paths, ())

    def test_backend_image_and_release_inputs_require_deploy(self) -> None:
        runtime_paths = (
            "pyproject.toml",
            "uv.lock",
            "server/config/settings/production.py",
            "server/identity/migrations/0005_attribution.py",
            "api/openapi.json",
            "api/fixtures/catalog.json",
            "data/venues/venues-v1/venues-v1.jsonl",
            "docs/privacy-policy.md",
            "docs/model/cover-historical-v1-evaluation.json",
            ".dockerignore",
            ".gcloudignore",
            ".github/workflows/deploy.yml",
            "ops/container/Dockerfile",
            "ops/cloudrun/prod-service.yaml",
            "ops/deployment/deploy-cloud-run.sh",
            "scripts/release/classify_runtime_changes.py",
            "scripts/release/service_release.py",
            "scripts/ci/classify_migrations.py",
            "scripts/ci/migration_evidence.py",
        )

        for path in runtime_paths:
            with self.subTest(path=path):
                decision = classify_paths([path])
                self.assertTrue(decision.deploy)
                self.assertEqual(decision.reason, "runtime_changes")
                self.assertEqual(decision.runtime_paths, (path,))

    def test_ignored_data_sources_and_release_tests_do_not_deploy(self) -> None:
        decision = classify_paths(
            [
                "data/deals/historical-deals-v1/source/raw.jsonl",
                "data/cover/cache/candidate.json",
                "scripts/release/test_service_release.py",
                "scripts/release/__pycache__/service_release.cpython-314.pyc",
            ]
        )

        self.assertFalse(decision.deploy)

    def test_server_test_directories_do_not_require_a_runtime_deploy(self) -> None:
        paths = (
            "server/covers/tests/test_api.py",
            "server/identity/tests/__init__.py",
        )

        decision = classify_paths(paths)

        self.assertFalse(decision.deploy)
        self.assertEqual(decision.reason, "no_runtime_changes")
        self.assertEqual(decision.runtime_paths, ())

    def test_server_runtime_config_and_migrations_remain_fail_safe(self) -> None:
        paths = (
            "server/config/settings/production.py",
            "server/covers/migrations/0002_report.py",
            "server/covers/services.py",
        )

        decision = classify_paths(paths)

        self.assertTrue(decision.deploy)
        self.assertEqual(decision.runtime_paths, paths)


class RepositoryRangeDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = GitRepository()

    def tearDown(self) -> None:
        self.repository.close()

    def test_valid_range_uses_name_status_including_deletions(self) -> None:
        before = self.repository.commit("server/example.py", "value = 1\n", "baseline")
        after_docs = self.repository.commit(
            "docs/runbooks/notes.md", "text\n", "documentation"
        )

        docs_decision = decide_repository_range(
            self.repository.path, before=before, after=after_docs
        )

        self.assertFalse(docs_decision.deploy)
        self.assertEqual(docs_decision.changed_paths, ("docs/runbooks/notes.md",))

        (self.repository.path / "server/example.py").unlink()
        _git(self.repository.path, "add", "--all")
        _git(self.repository.path, "commit", "--message", "delete runtime module")
        after_delete = _git(self.repository.path, "rev-parse", "HEAD")

        deletion_decision = decide_repository_range(
            self.repository.path, before=after_docs, after=after_delete
        )
        self.assertTrue(deletion_decision.deploy)
        self.assertEqual(deletion_decision.runtime_paths, ("server/example.py",))

    def test_initial_commit_without_parent_forces_deploy(self) -> None:
        initial = self.repository.commit("docs/readme.md", "text\n", "initial")

        decision = decide_repository_range(
            self.repository.path, before=ZERO_SHA, after=initial
        )

        self.assertTrue(decision.deploy)
        self.assertEqual(decision.reason, "initial_main_baseline")
        self.assertEqual(decision.changed_paths, ("docs/readme.md",))

    def test_missing_previous_commit_fails_safe_to_deploy(self) -> None:
        self.repository.commit("docs/readme.md", "one\n", "initial")
        after = self.repository.commit("docs/readme.md", "two\n", "docs")

        decision = decide_repository_range(
            self.repository.path, before="f" * 40, after=after
        )

        self.assertTrue(decision.deploy)
        self.assertEqual(decision.reason, "previous_commit_unavailable")

    def test_missing_target_commit_fails_safe_to_deploy(self) -> None:
        before = self.repository.commit("docs/readme.md", "one\n", "initial")

        decision = decide_repository_range(
            self.repository.path, before=before, after="e" * 40
        )

        self.assertTrue(decision.deploy)
        self.assertEqual(decision.reason, "target_commit_unavailable")

    def test_non_ancestor_previous_commit_fails_safe_to_deploy(self) -> None:
        before = self.repository.commit("docs/readme.md", "main\n", "main")
        _git(self.repository.path, "checkout", "--orphan", "replacement")
        for child in self.repository.path.iterdir():
            if child.name != ".git" and child.is_file():
                child.unlink()
        after = self.repository.commit("docs/readme.md", "replacement\n", "replacement")

        decision = decide_repository_range(
            self.repository.path, before=before, after=after
        )

        self.assertTrue(decision.deploy)
        self.assertEqual(decision.reason, "previous_commit_not_ancestor")


class CommandOutputTests(unittest.TestCase):
    def test_command_records_noop_in_github_output_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output = root / "output"
            summary = root / "summary"
            decision = RuntimeDecision(
                deploy=False,
                reason="no_runtime_changes",
                changed_paths=("ios/App.swift", "docs/readme.md"),
                runtime_paths=(),
            )

            with patch(
                "classify_runtime_changes.decide_repository_range",
                return_value=decision,
            ):
                result = main(
                    [
                        "--repository",
                        str(root),
                        "--before",
                        "a" * 40,
                        "--after",
                        "b" * 40,
                        "--github-output",
                        str(output),
                        "--github-summary",
                        str(summary),
                    ]
                )

            self.assertEqual(result, 0)
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "deploy=false\nreason=no_runtime_changes\nchanged_count=2\nruntime_count=0\n",
            )
            summary_text = summary.read_text(encoding="utf-8")
            self.assertIn("Production deployment: no-op", summary_text)
            self.assertIn(
                "No GCP authentication, build, migration, or deploy will run.",
                summary_text,
            )
            self.assertIn("`ios/App.swift`", summary_text)

    def test_command_records_fail_safe_deploy_without_noop_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output = root / "output"
            summary = root / "summary"
            decision = RuntimeDecision(
                deploy=True,
                reason="previous_commit_unavailable",
                changed_paths=(),
                runtime_paths=(),
            )

            with patch(
                "classify_runtime_changes.decide_repository_range",
                return_value=decision,
            ):
                result = main(
                    [
                        "--repository",
                        str(root),
                        "--before",
                        "a" * 40,
                        "--after",
                        "b" * 40,
                        "--github-output",
                        str(output),
                        "--github-summary",
                        str(summary),
                    ]
                )

            self.assertEqual(result, 0)
            self.assertIn("deploy=true", output.read_text(encoding="utf-8"))
            summary_text = summary.read_text(encoding="utf-8")
            self.assertIn("fail-safe release path will run", summary_text)
            self.assertNotIn("No GCP authentication", summary_text)


if __name__ == "__main__":
    unittest.main()
