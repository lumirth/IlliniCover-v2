from __future__ import annotations

import unittest

from verify_release_resource import environment, secret_environment


class VerifyReleaseResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.container = {
            "env": [
                {"name": "CODE_REVISION", "value": "a" * 40},
                {
                    "name": "ILLINICOVER_SECRETS_JSON",
                    "valueFrom": {
                        "secretKeyRef": {"name": "illinicover-web", "key": "7"}
                    },
                },
            ]
        }

    def test_projects_plain_environment(self) -> None:
        self.assertEqual(environment(self.container), {"CODE_REVISION": "a" * 40})

    def test_projects_exact_numeric_secret_reference(self) -> None:
        self.assertEqual(
            secret_environment(self.container),
            {"ILLINICOVER_SECRETS_JSON": ("illinicover-web", "7")},
        )


if __name__ == "__main__":
    unittest.main()
