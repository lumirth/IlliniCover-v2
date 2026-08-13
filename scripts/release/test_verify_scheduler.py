from __future__ import annotations

import unittest

from verify_scheduler import discover_state, scheduler_projection


class DiscoverSchedulerStateTests(unittest.TestCase):
    def test_absent_scheduler_is_distinct_from_an_api_error(self) -> None:
        self.assertEqual(discover_state([], "illinicover-nightly"), "ABSENT")

    def test_exact_scheduler_state_is_returned(self) -> None:
        resources = [
            {
                "name": "projects/illinicover/locations/us-east4/jobs/other",
                "state": "ENABLED",
            },
            {
                "name": "projects/illinicover/locations/us-east4/jobs/illinicover-nightly",
                "state": "PAUSED",
            },
        ]

        self.assertEqual(discover_state(resources, "illinicover-nightly"), "PAUSED")

    def test_unknown_state_fails_closed(self) -> None:
        resources = [{"name": "jobs/illinicover-nightly", "state": "STATE_UNSPECIFIED"}]

        with self.assertRaisesRegex(ValueError, "invalid state"):
            discover_state(resources, "illinicover-nightly")


class SchedulerProjectionTests(unittest.TestCase):
    def test_release_fields_include_paused_state(self) -> None:
        resource = {
            "schedule": "17 10 * * *",
            "timeZone": "America/Chicago",
            "state": "PAUSED",
            "httpTarget": {
                "uri": "https://run.googleapis.com/v2/nightly:run",
                "httpMethod": "POST",
                "oauthToken": {"serviceAccountEmail": "jobs@example.test"},
            },
        }

        self.assertEqual(
            scheduler_projection(resource),
            {
                "schedule": "17 10 * * *",
                "timeZone": "America/Chicago",
                "uri": "https://run.googleapis.com/v2/nightly:run",
                "httpMethod": "POST",
                "serviceAccount": "jobs@example.test",
                "state": "PAUSED",
            },
        )


if __name__ == "__main__":
    unittest.main()
