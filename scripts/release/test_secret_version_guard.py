from __future__ import annotations

import unittest

from secret_version_guard import (
    SecretVersion,
    SecretVersionError,
    check_headroom,
    retire,
    retirement_plan,
)


def version(secret: str, number: int, state: str = "ENABLED") -> SecretVersion:
    return SecretVersion(secret=secret, version=str(number), state=state)


class FakeCloud:
    def __init__(self, versions: list[SecretVersion]) -> None:
        self.items = {(item.secret, item.version): item for item in versions}
        self.actions: list[tuple[str, str, str]] = []

    def secret_names(self, project: str) -> list[str]:
        del project
        return sorted({secret for secret, _ in self.items})

    def versions(self, project: str, secret: str) -> list[SecretVersion]:
        del project
        return [item for item in self.items.values() if item.secret == secret]

    def disable(self, project: str, item: SecretVersion) -> None:
        del project
        self.actions.append(("disable", item.secret, item.version))
        self.items[(item.secret, item.version)] = version(
            item.secret, int(item.version), "DISABLED"
        )

    def destroy(self, project: str, item: SecretVersion) -> None:
        del project
        self.actions.append(("destroy", item.secret, item.version))
        self.items[(item.secret, item.version)] = version(
            item.secret, int(item.version), "DESTROYED"
        )

    def state(self, project: str, item: SecretVersion) -> str:
        del project
        return self.items[(item.secret, item.version)].state


class SecretVersionGuardTests(unittest.TestCase):
    def test_allows_two_bounded_preview_candidates_from_settled_free_inventory(self) -> None:
        active = [version(f"secret-{index}", 1) for index in range(6)]
        self.assertEqual(
            check_headroom(
                active,
                pending=2,
                settled_ceiling=6,
                rotation_ceiling=8,
            ),
            (6, 8),
        )

    def test_rejects_disabled_billable_versions_before_another_rotation(self) -> None:
        with self.assertRaisesRegex(SecretVersionError, "disabled versions are still billable"):
            check_headroom(
                [version("web", 1, "DISABLED")],
                pending=1,
                settled_ceiling=6,
                rotation_ceiling=8,
            )

    def test_rejects_multiple_enabled_versions_before_another_rotation(self) -> None:
        with self.assertRaisesRegex(SecretVersionError, "more than 1 active versions"):
            check_headroom(
                [version("web", 1), version("web", 2)],
                pending=1,
                settled_ceiling=6,
                rotation_ceiling=8,
            )

    def test_release_may_accept_one_explicit_candidate_per_secret(self) -> None:
        self.assertEqual(
            check_headroom(
                [version("web", 1), version("web", 2)],
                pending=0,
                settled_ceiling=6,
                rotation_ceiling=8,
                allow_candidates=True,
            ),
            (2, 2),
        )

    def test_release_rejects_more_than_one_candidate_for_a_secret(self) -> None:
        with self.assertRaisesRegex(SecretVersionError, "more than 2 active versions"):
            check_headroom(
                [version("web", 1), version("web", 2), version("web", 3)],
                pending=0,
                settled_ceiling=6,
                rotation_ceiling=8,
                allow_candidates=True,
            )

    def test_rejects_projected_inventory_above_bounded_rotation_ceiling(self) -> None:
        with self.assertRaisesRegex(SecretVersionError, "above bounded rotation ceiling"):
            check_headroom(
                [version(f"secret-{index}", 1) for index in range(6)],
                pending=3,
                settled_ceiling=6,
                rotation_ceiling=8,
            )

    def test_external_billing_account_inventory_consumes_headroom(self) -> None:
        with self.assertRaisesRegex(SecretVersionError, "above current ceiling"):
            check_headroom(
                [version(f"secret-{index}", 1) for index in range(6)],
                pending=0,
                settled_ceiling=6,
                rotation_ceiling=8,
                external_active=1,
            )

    def test_retirement_keeps_exact_enabled_versions_and_only_active_predecessors(self) -> None:
        versions = [
            version("web", 1, "DESTROYED"),
            version("web", 2),
            version("web", 3),
            version("migrate", 4, "DISABLED"),
            version("migrate", 5),
        ]
        self.assertEqual(
            retirement_plan(versions, {"web": "3", "migrate": "5"}),
            [version("migrate", 4, "DISABLED"), version("web", 2)],
        )

    def test_retirement_refuses_to_remove_anything_if_keep_is_not_enabled(self) -> None:
        with self.assertRaisesRegex(SecretVersionError, "retained version is not enabled"):
            retirement_plan([version("web", 3, "DISABLED")], {"web": "3"})

    def test_retirement_disables_and_reads_back_before_destroying(self) -> None:
        cloud = FakeCloud([version("web", 6), version("web", 7)])
        self.assertEqual(
            retire(cloud, "project", {"web": "7"}, execute=True),
            [version("web", 6)],
        )
        self.assertEqual(
            cloud.actions,
            [("disable", "web", "6"), ("destroy", "web", "6")],
        )
        self.assertEqual(cloud.state("project", version("web", 6)), "DESTROYED")


if __name__ == "__main__":
    unittest.main()
