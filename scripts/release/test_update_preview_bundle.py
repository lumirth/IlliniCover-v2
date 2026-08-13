from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from update_preview_bundle import main


class PreviewBundleTests(unittest.TestCase):
    def run_update(self, mode: str) -> dict[str, str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            target = root / "target.json"
            source.write_text(
                json.dumps(
                    {
                        "DJANGO_SECRET_KEY": "preview-only",
                        "DATABASE_URL": "postgresql://old/pooled",
                        "DATABASE_URL_DIRECT": "postgresql://old/direct",
                    }
                )
            )
            with (
                patch.dict(os.environ, {"PREVIEW_DATABASE_URL": "postgresql://new/value"}),
                patch(
                    "sys.argv",
                    [
                        "update_preview_bundle.py",
                        "--input",
                        str(source),
                        "--output",
                        str(target),
                        "--mode",
                        mode,
                    ],
                ),
            ):
                self.assertEqual(main(), 0)
            return json.loads(target.read_text())

    def test_web_bundle_contains_only_pooled_database_capability(self) -> None:
        bundle = self.run_update("pooled")
        self.assertEqual(bundle["DATABASE_URL"], "postgresql://new/value")
        self.assertNotIn("DATABASE_URL_DIRECT", bundle)

    def test_migration_bundle_contains_only_direct_database_capability(self) -> None:
        bundle = self.run_update("direct")
        self.assertEqual(bundle["DATABASE_URL_DIRECT"], "postgresql://new/value")
        self.assertNotIn("DATABASE_URL", bundle)


if __name__ == "__main__":
    unittest.main()
