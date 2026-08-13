from __future__ import annotations

import unittest

from classify_changes import classify


class ChangeClassificationTests(unittest.TestCase):
    def test_docs_only_avoids_application_and_database_work(self) -> None:
        result = classify(["docs/architecture.md"])
        self.assertFalse(any(result.values()))

    def test_server_schema_change_selects_backend_contract_and_migrations(self) -> None:
        result = classify(
            [
                "server/covers/schemas.py",
                "server/covers/migrations/0007_release.py",
            ]
        )
        self.assertTrue(result["backend"])
        self.assertTrue(result["contract"])
        self.assertTrue(result["fixtures"])
        self.assertTrue(result["migrations"])
        self.assertFalse(result["ops"])

    def test_ops_change_does_not_select_backend(self) -> None:
        result = classify(["ops/cloudrun/prod-service.yaml"])
        self.assertTrue(result["ops"])
        self.assertFalse(result["backend"])

    def test_cloud_build_context_ignore_files_select_ops(self) -> None:
        for path in (".gcloudignore", ".dockerignore"):
            with self.subTest(path=path):
                result = classify([path])
                self.assertTrue(result["ops"])
                self.assertFalse(result["backend"])

    def test_model_change_selects_backend_and_data(self) -> None:
        result = classify(["server/covers/modeling/historical.py"])
        self.assertTrue(result["backend"])
        self.assertTrue(result["data"])

    def test_public_response_service_selects_fixture_regeneration(self) -> None:
        result = classify(["server/covers/services.py"])
        self.assertTrue(result["backend"])
        self.assertTrue(result["fixtures"])

    def test_resolver_and_model_changes_select_fixture_regeneration(self) -> None:
        result = classify(
            ["server/covers/modeling/resolver.py", "server/venues/models.py"]
        )
        self.assertTrue(result["fixtures"])

    def test_runtime_config_change_does_not_select_fixture_regeneration(self) -> None:
        result = classify(["server/config/logging.py"])
        self.assertFalse(result["fixtures"])

    def test_fixture_settings_producers_select_fixture_regeneration(self) -> None:
        for path in (
            "server/config/settings/base.py",
            "server/config/settings/fixtures.py",
        ):
            with self.subTest(path=path):
                self.assertTrue(classify([path])["fixtures"])

    def test_canonical_seed_command_selects_fixture_regeneration(self) -> None:
        result = classify(
            ["server/operations/management/commands/seed_visual_acceptance.py"]
        )
        self.assertTrue(result["fixtures"])

    def test_paths_remain_classified_when_their_git_status_is_deleted(self) -> None:
        result = classify(
            [
                "server/covers/migrations/0007_release.py",
                "api/fixtures/catalog.json",
                "ops/cloudrun/prod-service.yaml",
                "ios/IlliniCover/APIClient.swift",
            ]
        )
        self.assertTrue(result["backend"])
        self.assertTrue(result["migrations"])
        self.assertTrue(result["fixtures"])
        self.assertTrue(result["ops"])
        self.assertTrue(result["ios"])


if __name__ == "__main__":
    unittest.main()
