from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from classify_migrations import classify_changed_migrations, risky_operations, risky_paths


def git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def commit(repository: Path, message: str) -> str:
    git(repository, "add", "--all")
    git(repository, "commit", "--message", message)
    return git(repository, "rev-parse", "HEAD")


def write_migration(path: Path, operation: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "from django.db import migrations\n"
        "class Migration(migrations.Migration):\n"
        f"    operations = [migrations.{operation}]\n",
        encoding="utf-8",
    )


class MigrationRiskTests(unittest.TestCase):
    def classify(self, operation: str) -> tuple[str, ...]:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "0002_change.py"
            write_migration(path, operation)
            return risky_operations(path)

    def test_additive_operation_is_normal(self) -> None:
        self.assertEqual(self.classify("AddField(model_name='x', name='y', field=None)"), ())

    def test_data_and_removal_operations_require_exceptional_review(self) -> None:
        self.assertEqual(self.classify("RemoveField(model_name='x', name='y')"), ("RemoveField",))
        self.assertEqual(self.classify("RunPython(forwards)"), ("RunPython",))

    def test_compatibility_changing_operations_require_exceptional_review(self) -> None:
        for operation in (
            "AlterField(model_name='x', name='y', field=None)",
            "RenameField(model_name='x', old_name='y', new_name='z')",
            "RenameModel(old_name='X', new_name='Y')",
            "AddConstraint(model_name='x', constraint=None)",
            "RemoveConstraint(model_name='x', name='unique_x')",
            "RemoveIndex(model_name='x', name='x_idx')",
            "RenameIndex(model_name='x', old_name='x_idx', new_name='y_idx')",
            "SeparateDatabaseAndState(database_operations=[], state_operations=[])",
        ):
            with self.subTest(operation=operation):
                self.assertTrue(self.classify(operation))

    def test_non_schema_metadata_and_additive_index_remain_normal(self) -> None:
        self.assertEqual(
            self.classify("AlterModelOptions(name='x', options={'ordering': ['id']})"),
            (),
        )
        self.assertEqual(
            self.classify("AddIndex(model_name='x', index=None)"),
            (),
        )

    def test_deleted_migration_is_always_exceptional(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "0002_deleted.py"
            self.assertEqual(risky_paths([missing]), [(missing, ("DeletedMigration",))])

    def test_exact_protected_initializer_allows_only_the_first_source_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            git(repository, "init", "--initial-branch=main")
            git(repository, "config", "user.name", "Migration classifier test")
            git(repository, "config", "user.email", "migration-classifier@example.test")
            marker = repository / ".github" / "INITIALIZED"
            marker.parent.mkdir(parents=True)
            marker.write_text(
                "IlliniCover v2 repository initialized. "
                "Source enters through a protected pull request.\n",
                encoding="utf-8",
            )
            base = commit(repository, "initialize protected repository")
            historical = repository / "server" / "example" / "migrations" / "0001_initial.py"
            write_migration(historical, "RunPython(forwards)")

            self.assertEqual(
                classify_changed_migrations(
                    [historical], repository=repository, base=base
                ),
                [],
            )

            imported = commit(repository, "import reviewed source")
            later = repository / "server" / "example" / "migrations" / "0002_remove.py"
            write_migration(later, "RemoveField(model_name='x', name='y')")
            self.assertEqual(
                classify_changed_migrations([later], repository=repository, base=imported),
                [(later, ("RemoveField",))],
            )

    def test_similar_but_noncanonical_base_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            git(repository, "init", "--initial-branch=main")
            git(repository, "config", "user.name", "Migration classifier test")
            git(repository, "config", "user.email", "migration-classifier@example.test")
            marker = repository / ".github" / "INITIALIZED"
            marker.parent.mkdir(parents=True)
            marker.write_text("generic empty repository\n", encoding="utf-8")
            base = commit(repository, "other repository baseline")
            risky = repository / "server" / "example" / "migrations" / "0001_initial.py"
            write_migration(risky, "RunPython(forwards)")

            self.assertEqual(
                classify_changed_migrations([risky], repository=repository, base=base),
                [(risky, ("RunPython",))],
            )

    def test_recreated_initializer_tree_after_a_parent_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            git(repository, "init", "--initial-branch=main")
            git(repository, "config", "user.name", "Migration classifier test")
            git(repository, "config", "user.email", "migration-classifier@example.test")
            readme = repository / "README.md"
            readme.write_text("first commit\n", encoding="utf-8")
            commit(repository, "unrelated root")
            readme.unlink()
            marker = repository / ".github" / "INITIALIZED"
            marker.parent.mkdir(parents=True)
            marker.write_text(
                "IlliniCover v2 repository initialized. "
                "Source enters through a protected pull request.\n",
                encoding="utf-8",
            )
            recreated = commit(repository, "recreate marker tree")
            risky = repository / "server" / "example" / "migrations" / "0001_initial.py"
            write_migration(risky, "RunPython(forwards)")

            self.assertEqual(
                classify_changed_migrations(
                    [risky], repository=repository, base=recreated
                ),
                [(risky, ("RunPython",))],
            )


if __name__ == "__main__":
    unittest.main()
