from __future__ import annotations

import unittest

from cloud_run_release_state import (
    discover_resource,
    job_config,
    job_replace_manifest,
    new_image_revisions,
    resource_image,
    revision_names,
)

OLD_IMAGE = "us-east5-docker.pkg.dev/illinicover/illinicover/backend@sha256:" + "a" * 64
NEW_IMAGE = "us-east5-docker.pkg.dev/illinicover/illinicover/backend@sha256:" + "b" * 64


def resource(name: str, image: str) -> dict[str, object]:
    return {
        "metadata": {"name": name},
        "spec": {"containers": [{"image": image}]},
    }


class CloudRunReleaseStateTests(unittest.TestCase):
    def test_discovers_one_exact_resource_without_treating_list_failure_as_absence(self) -> None:
        resources = [resource("illinicover-nightly", OLD_IMAGE)]

        self.assertEqual(discover_resource(resources, "illinicover-nightly"), "PRESENT")
        self.assertEqual(discover_resource(resources, "illinicover-refresh"), "ABSENT")
        with self.assertRaisesRegex(ValueError, "JSON list"):
            discover_resource({}, "illinicover-nightly")

    def test_reads_one_exact_digest_pinned_container_image(self) -> None:
        self.assertEqual(resource_image(resource("illinicover-nightly", OLD_IMAGE)), OLD_IMAGE)

        with self.assertRaisesRegex(ValueError, "digest-pinned"):
            resource_image(resource("illinicover-nightly", "backend:latest"))

    def test_selects_only_new_revisions_for_the_exact_release_image(self) -> None:
        before = {"illinicover-api-00001-old"}
        resources = [
            resource("illinicover-api-00002-candidate", NEW_IMAGE),
            resource("illinicover-api-00001-old", OLD_IMAGE),
            resource("illinicover-api-00003-unrelated", OLD_IMAGE),
        ]

        self.assertEqual(
            revision_names(resources),
            (
                "illinicover-api-00001-old",
                "illinicover-api-00002-candidate",
                "illinicover-api-00003-unrelated",
            ),
        )
        self.assertEqual(
            new_image_revisions(resources, image=NEW_IMAGE, baseline=before),
            ("illinicover-api-00002-candidate",),
        )

    def test_rejects_duplicate_or_malformed_revision_metadata(self) -> None:
        duplicate = [
            resource("illinicover-api-00002-candidate", NEW_IMAGE),
            resource("illinicover-api-00002-candidate", NEW_IMAGE),
        ]

        with self.assertRaisesRegex(ValueError, "duplicate"):
            revision_names(duplicate)
        with self.assertRaisesRegex(ValueError, "metadata"):
            revision_names([{"spec": {"containers": []}}])
        with self.assertRaisesRegex(ValueError, "metadata"):
            revision_names([resource("--project=other", NEW_IMAGE)])

    def test_job_rollback_manifest_and_comparison_cover_the_complete_runtime_spec(self) -> None:
        value = {
            "apiVersion": "run.googleapis.com/v1",
            "kind": "Job",
            "metadata": {
                "name": "illinicover-nightly",
                "generation": 9,
                "annotations": {
                    "run.googleapis.com/binary-authorization": "default",
                    "run.googleapis.com/breakglass": "emergency release",
                    "run.googleapis.com/launch-stage": "BETA",
                    "example.com/release-policy": "bounded",
                    "run.googleapis.com/client-name": "gcloud",
                    "run.googleapis.com/client-version": "580.0.0",
                    "run.googleapis.com/creator": "creator@example.invalid",
                    "run.googleapis.com/lastModifier": "modifier@example.invalid",
                    "run.googleapis.com/operation-id": "generated-operation",
                },
                "labels": {
                    "illinicover-owner": "operations",
                    "example.com/policy": "strict",
                    "client.knative.dev/nonce": "generated",
                    "cloud.googleapis.com/location": "us-east5",
                    "run.googleapis.com/lastUpdatedTime": "2026-08-12T00:00:00Z",
                    "run.googleapis.com/satisfiesPzs": "true",
                },
            },
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "run.googleapis.com/execution-environment": "gen2",
                            "run.googleapis.com/client-version": "580.0.0",
                            "run.googleapis.com/vpc-access-connector": (
                                "projects/p/locations/r/connectors/c"
                            ),
                        },
                        "labels": {
                            "client.knative.dev/nonce": "random",
                            "illinicover-role": "nightly",
                        },
                    },
                    "spec": {
                        "taskCount": 1,
                        "template": {
                            "spec": {
                                "containers": [{"image": OLD_IMAGE, "command": ["python"]}],
                                "serviceAccountName": "jobs@example.invalid",
                                "timeoutSeconds": "900",
                            }
                        },
                    },
                }
            },
        }

        config = job_config(value)
        manifest = job_replace_manifest(value)

        self.assertEqual(config["spec"]["template"]["spec"]["taskCount"], 1)
        expected_metadata = {
            "name": "illinicover-nightly",
            "annotations": {
                "run.googleapis.com/binary-authorization": "default",
                "run.googleapis.com/breakglass": "emergency release",
                "run.googleapis.com/launch-stage": "BETA",
                "example.com/release-policy": "bounded",
            },
            "labels": {
                "illinicover-owner": "operations",
                "example.com/policy": "strict",
            },
        }
        self.assertEqual(config["metadata"], expected_metadata)
        self.assertEqual(manifest["metadata"], expected_metadata)
        self.assertNotIn("client.knative.dev/nonce", str(manifest))
        self.assertNotIn("client-version", str(manifest))
        self.assertNotIn("lastUpdatedTime", str(manifest))
        self.assertNotIn("operation-id", str(manifest))
        self.assertEqual(
            manifest["spec"]["template"]["metadata"],
            {
                "annotations": {
                    "run.googleapis.com/execution-environment": "gen2",
                    "run.googleapis.com/vpc-access-connector": (
                        "projects/p/locations/r/connectors/c"
                    ),
                },
                "labels": {"illinicover-role": "nightly"},
            },
        )


if __name__ == "__main__":
    unittest.main()
