from __future__ import annotations

import unittest

from service_release import discover_service, serving_revision, tagged_target


class ServiceReleaseProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resource = {
            "status": {
                "traffic": [
                    {"revisionName": "api-old", "percent": 100},
                    {
                        "revisionName": "api-next",
                        "percent": 0,
                        "tag": "candidate-abc",
                        "url": "https://candidate-abc---api.example.run.app",
                    },
                ]
            }
        }

    def test_projects_single_serving_revision(self) -> None:
        self.assertEqual(serving_revision(self.resource), "api-old")

    def test_projects_candidate_revision_and_url(self) -> None:
        self.assertEqual(
            tagged_target(self.resource, "candidate-abc"),
            ("api-next", "https://candidate-abc---api.example.run.app"),
        )

    def test_tagged_revision_may_also_be_the_only_serving_target(self) -> None:
        self.resource["status"]["traffic"] = [
            {
                "revisionName": "api-next",
                "percent": 100,
                "tag": "candidate-abc",
                "url": "https://candidate-abc---api.example.run.app",
            }
        ]
        self.assertEqual(serving_revision(self.resource), "api-next")

    def test_split_traffic_fails_closed(self) -> None:
        self.resource["status"]["traffic"] = [
            {"revisionName": "api-a", "percent": 50},
            {"revisionName": "api-b", "percent": 50},
        ]
        with self.assertRaisesRegex(ValueError, "exactly one"):
            serving_revision(self.resource)

    def test_service_discovery_distinguishes_absent_from_present(self) -> None:
        resources = [{"metadata": {"name": "illinicover-api"}}]
        self.assertEqual(discover_service(resources, "illinicover-api"), "PRESENT")
        self.assertEqual(discover_service(resources, "other"), "ABSENT")


if __name__ == "__main__":
    unittest.main()
