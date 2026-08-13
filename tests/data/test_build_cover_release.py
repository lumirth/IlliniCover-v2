from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts/data/build_cover_release.py"
SOURCE_PATH = REPOSITORY_ROOT / "data/cover/recovered-cover-v1/source/recovered_history.json"

SPEC = importlib.util.spec_from_file_location("build_cover_release", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CoverReleaseTest(unittest.TestCase):
    def test_release_is_deterministic_and_preserves_raw_prices(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            release_dir = Path(temporary_directory) / "recovered-cover-v1"
            (release_dir / "source").mkdir(parents=True)
            shutil.copyfile(SOURCE_PATH, release_dir / "source/recovered_history.json")

            first = MODULE.build_release(release_dir, SCRIPT_PATH)
            first_hashes = {
                name: MODULE.sha256(release_dir / name)
                for name in (
                    "cover-observations-v1.jsonl",
                    "rejections-v1.jsonl",
                    "normalization-receipt.json",
                    "manifest.json",
                )
            }
            second = MODULE.build_release(release_dir, SCRIPT_PATH)
            second_hashes = {name: MODULE.sha256(release_dir / name) for name in first_hashes}

            self.assertEqual(first_hashes, second_hashes)
            self.assertEqual(first["receipt"], second["receipt"])
            self.assertEqual(first["receipt"]["rows_seen"], 1200)
            self.assertEqual(first["receipt"]["rows_accepted"], 1199)
            self.assertEqual(first["receipt"]["rows_rejected"], 1)
            self.assertEqual(first["receipt"]["unique_source_record_keys"], 1199)
            self.assertEqual(
                first_hashes["cover-observations-v1.jsonl"],
                "aaab73ccf1a825e1192f04ff00a0affcf0fb877da3d744ed3a6c33d60ed8674e",
            )

            rows = [
                json.loads(line)
                for line in (release_dir / "cover-observations-v1.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(rows), 1199)
            self.assertEqual(len({row["source_record_key"] for row in rows}), 1199)
            self.assertEqual(sum(row["reported_price_cents"] == 200 for row in rows), 1)
            self.assertEqual(sum(row["reported_price_cents"] == 1200 for row in rows), 1)
            self.assertTrue(all("submitted_at" not in row and "user_id" not in row for row in rows))

            rejection = json.loads((release_dir / "rejections-v1.jsonl").read_text())
            self.assertEqual(rejection["reason"], "negative_cover_price")
            self.assertEqual(rejection["source_price"], {"integerValue": "-5"})
            self.assertEqual(
                rejection["source_record_key"],
                "projects/icover-41a28/databases/(default)/documents/"
                "Brothers Logs/0G88djMz5U3zVnFiTWFL",
            )

    def test_manifest_pins_the_raw_export(self) -> None:
        manifest = json.loads(
            (REPOSITORY_ROOT / "data/cover/recovered-cover-v1/manifest.json").read_text()
        )
        source = next(item for item in manifest["artifacts"] if item["path"].startswith("source/"))
        self.assertEqual(source["rows"], 1200)
        self.assertEqual(source["bytes"], 447852)
        self.assertEqual(
            source["sha256"],
            "05d7cbad141b0639179059d2cd863e275ab811c991ed29c94a1cccf0b23929c9",
        )


if __name__ == "__main__":
    unittest.main()
