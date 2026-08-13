from __future__ import annotations

import unittest
from unittest.mock import patch

from artifact_image_cleanup import GcloudRegistry, cleanup_image

ROOT = "sha256:" + "a" * 64
IMAGE = "sha256:" + "b" * 64
ATTESTATION = "sha256:" + "c" * 64


class FakeRegistry:
    def __init__(self) -> None:
        self.manifests = {
            ROOT: {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [
                    {"digest": IMAGE},
                    {"digest": ATTESTATION},
                ],
            },
            IMAGE: {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
            },
            ATTESTATION: {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
            },
        }
        self.deleted: list[str] = []
        self.attachments_by_digest: dict[str, list[str]] = {}
        self.deleted_attachments: list[str] = []
        self.keep_attachments = False

    def manifest(self, digest: str):
        return self.manifests.get(digest)

    def delete_manifest(self, digest: str) -> None:
        self.deleted.append(digest)
        self.manifests.pop(digest, None)

    def attachments(self, digest: str) -> tuple[str, ...]:
        return tuple(self.attachments_by_digest.get(digest, []))

    def delete_attachment(self, name: str) -> None:
        self.deleted_attachments.append(name)
        if self.keep_attachments:
            return
        for attachments in self.attachments_by_digest.values():
            if name in attachments:
                attachments.remove(name)


class ArtifactImageCleanupTests(unittest.TestCase):
    def test_attachment_inventory_uses_the_version_resource_name(self) -> None:
        registry = GcloudRegistry(
            project="illinicover",
            location="us-east5",
            repository="illinicover",
            package="backend",
        )
        target = (
            "projects/illinicover/locations/us-east5/repositories/illinicover/"
            f"packages/backend/versions/{ROOT}"
        )

        with patch.object(registry, "_gcloud", return_value="[]") as gcloud:
            registry.attachments(ROOT)

        self.assertIn(target, gcloud.call_args.args)

    def test_cleanup_deletes_and_verifies_the_index_image_and_attestation(self) -> None:
        registry = FakeRegistry()

        deleted = cleanup_image(registry, ROOT, execute=True)

        self.assertEqual(deleted, (ROOT, IMAGE, ATTESTATION))
        self.assertEqual(registry.deleted, [IMAGE, ATTESTATION, ROOT])
        self.assertFalse(registry.manifests)

    def test_cleanup_removes_and_verifies_artifact_registry_attachments(self) -> None:
        registry = FakeRegistry()
        attachment = (
            "projects/illinicover/locations/us-east5/repositories/illinicover/"
            "attachments/build-provenance"
        )
        registry.attachments_by_digest[ROOT] = [attachment]

        cleanup_image(registry, ROOT, execute=True)

        self.assertEqual(registry.deleted_attachments, [attachment])
        self.assertEqual(registry.attachments(ROOT), ())

    def test_cleanup_rejects_a_non_digest_child_before_deleting_anything(self) -> None:
        registry = FakeRegistry()
        registry.manifests[ROOT]["manifests"] = [{"digest": "latest"}]

        with self.assertRaisesRegex(ValueError, "valid sha256 digest"):
            cleanup_image(registry, ROOT, execute=True)

        self.assertEqual(registry.deleted, [])
        self.assertEqual(registry.deleted_attachments, [])

    def test_cleanup_does_not_delete_manifests_when_an_attachment_remains(self) -> None:
        registry = FakeRegistry()
        registry.attachments_by_digest[ROOT] = ["projects/p/locations/l/attachments/a"]
        registry.keep_attachments = True

        with self.assertRaisesRegex(RuntimeError, "attachments remain"):
            cleanup_image(registry, ROOT, execute=True)

        self.assertEqual(registry.deleted, [])

    def test_cleanup_removes_root_attachments_after_a_partial_manifest_deletion(self) -> None:
        registry = FakeRegistry()
        registry.manifests.clear()
        attachment = "projects/p/locations/l/repositories/r/attachments/a"
        registry.attachments_by_digest[ROOT] = [attachment]

        cleanup_image(registry, ROOT, execute=True)

        self.assertEqual(registry.deleted_attachments, [attachment])
        self.assertEqual(registry.attachments(ROOT), ())


if __name__ == "__main__":
    unittest.main()
