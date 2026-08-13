from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = (
    REPOSITORY_ROOT / "data/cover/recovered-cover-v1/manifest.json",
    REPOSITORY_ROOT / "data/deals/historical-deals-v1/manifest.json",
    REPOSITORY_ROOT / "data/deals/deal-identities-v1/manifest.json",
    REPOSITORY_ROOT / "data/venues/venues-v1/manifest.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class ReleaseManifestTest(unittest.TestCase):
    def test_every_declared_artifact_matches_bytes_hash_and_rows(self) -> None:
        releases = set()
        for manifest_path in MANIFESTS:
            manifest = json.loads(manifest_path.read_text())
            self.assertNotIn(manifest["dataset_release"], releases)
            releases.add(manifest["dataset_release"])
            self.assertTrue(manifest["license_caveat"])
            self.assertTrue(manifest["privacy_caveat"])
            self.assertTrue(manifest["provenance"])
            for declared in manifest["artifacts"]:
                artifact = manifest_path.parent / declared["path"]
                self.assertTrue(artifact.is_file(), artifact)
                self.assertEqual(artifact.stat().st_size, declared["bytes"], artifact)
                self.assertEqual(sha256(artifact), declared["sha256"], artifact)
                if "rows" in declared:
                    if artifact.suffix == ".jsonl":
                        with artifact.open("rb") as handle:
                            actual_rows = sum(1 for _ in handle)
                    else:
                        source = json.loads(artifact.read_text())
                        actual_rows = sum(len(rows) for rows in source.values())
                    self.assertEqual(actual_rows, declared["rows"], artifact)


if __name__ == "__main__":
    unittest.main()
