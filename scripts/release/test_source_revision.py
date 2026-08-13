from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source_revision import framed_digest, validate_upload_paths

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class SourceRevisionTests(unittest.TestCase):
    def test_digest_is_order_independent_and_content_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.txt").write_bytes(b"alpha")
            (root / "b.txt").write_bytes(b"beta")

            first = framed_digest(root, ["a.txt", "b.txt"])
            reordered = framed_digest(root, ["b.txt", "a.txt"])
            self.assertEqual(first, reordered)

            (root / "b.txt").write_bytes(b"changed")
            self.assertNotEqual(first, framed_digest(root, ["a.txt", "b.txt"]))

    def test_digest_is_path_and_mode_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.txt").write_bytes(b"same")
            (root / "b.txt").write_bytes(b"same")
            a_digest = framed_digest(root, ["a.txt"])
            b_digest = framed_digest(root, ["b.txt"])
            self.assertNotEqual(a_digest, b_digest)

            (root / "a.txt").chmod(0o755)
            self.assertNotEqual(a_digest, framed_digest(root, ["a.txt"]))

    def test_local_evidence_and_type_cache_are_never_uploaded(self) -> None:
        gcloud_ignore = (REPOSITORY_ROOT / ".gcloudignore").read_text(encoding="utf-8")
        self.assertIn(".artifacts/", gcloud_ignore.splitlines())
        self.assertIn(".mypy_cache/", gcloud_ignore.splitlines())

        for ignore_name in (".gcloudignore", ".dockerignore", ".gitignore"):
            with self.subTest(ignore_name=ignore_name):
                ignore = (REPOSITORY_ROOT / ignore_name).read_text(encoding="utf-8")
                self.assertIn("gha-creds-*.json", ignore.splitlines())

        with self.assertRaisesRegex(RuntimeError, "forbidden local artifact"):
            validate_upload_paths(["server/config/health.py", ".artifacts/ios/run.xcresult"])
        with self.assertRaisesRegex(RuntimeError, "forbidden local artifact"):
            validate_upload_paths([".mypy_cache/3.14/cache.json"])
        with self.assertRaisesRegex(RuntimeError, "forbidden local artifact"):
            validate_upload_paths(["gha-creds-1234567890abcdef.json"])
        with self.assertRaisesRegex(RuntimeError, "forbidden local artifact"):
            validate_upload_paths(["nested/gha-creds-release.json"])


if __name__ == "__main__":
    unittest.main()
