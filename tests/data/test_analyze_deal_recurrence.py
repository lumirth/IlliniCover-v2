from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts/data/analyze_deal_recurrence.py"
DEAL_RELEASE = REPOSITORY_ROOT / "data/deals/historical-deals-v1"
IDENTITY_RELEASE = REPOSITORY_ROOT / "data/deals/deal-identities-v1"

SPEC = importlib.util.spec_from_file_location("analyze_deal_recurrence", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DealReleaseTest(unittest.TestCase):
    def test_release_rebuild_matches_checked_in_products(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            deal_dir = temporary_root / "historical-deals-v1"
            identity_dir = temporary_root / "deal-identities-v1"
            (deal_dir / "source").mkdir(parents=True)
            (identity_dir / "source").mkdir(parents=True)
            shutil.copyfile(
                DEAL_RELEASE / "source/plan-v1-deterministic.jsonl",
                deal_dir / "source/plan-v1-deterministic.jsonl",
            )
            shutil.copyfile(
                IDENTITY_RELEASE / "source/deal_canonical_registry.jsonl",
                identity_dir / "source/deal_canonical_registry.jsonl",
            )

            result = MODULE.build_release(deal_dir, identity_dir, SCRIPT_PATH)
            receipt = result["receipt"]
            selected = receipt["model_release"]
            descriptive = receipt["descriptive_analysis"]

            self.assertEqual(len(result["facts"]), 13_786)
            self.assertEqual(len(result["rejections"]), 72)
            self.assertEqual(
                MODULE.sha256(deal_dir / "historical-deals-v1.jsonl"),
                "a0c9222cb5a268001657adc679c13c36232aa1bbc10856144c8e68aa91e7e6dd",
            )
            self.assertEqual(
                MODULE.sha256(deal_dir / "rejections-v1.jsonl"),
                "f65f9dcfeffed0047c1672a6c35d16b642603841fde709d36291d879aa55ada5",
            )
            self.assertEqual(selected["name"], "deal_recurrence_v1")
            self.assertEqual(selected["selected_candidate"], "two_of_last_three_90d")
            self.assertEqual(selected["selected_backtest"]["target_nights"], 1483)
            self.assertEqual(selected["selected_backtest"]["precision"], 0.593016)
            self.assertEqual(selected["selected_backtest"]["recall"], 0.41663)
            self.assertEqual(selected["selected_backtest"]["f1"], 0.489416)
            self.assertEqual(descriptive["timing_kind_rows"]["unknown"], 6687)
            self.assertEqual(descriptive["identity"]["approved_drink_families_used"], 821)
            self.assertEqual(
                descriptive["confirmation_and_denial_behavior"]["structured_denials"], 0
            )
            self.assertFalse(receipt["reproducibility"]["paid_resources_used"])

    def test_unknown_timing_is_not_all_night(self) -> None:
        timing = MODULE.timing_fields(
            {
                "availability_cue": None,
                "end_time": None,
                "start_time": None,
                "timing_span": None,
            }
        )
        self.assertEqual(timing["timing_kind"], "unknown")

    def test_variant_selection_counts_distinct_nights(self) -> None:
        history = [
            (
                MODULE.date(2026, 1, 1),
                {"offer-a": {"deal-old"}, "offer-b": {"one-off"}},
            ),
            (MODULE.date(2026, 1, 8), {"offer-a": {"deal-old"}}),
            (MODULE.date(2026, 1, 15), {"offer-a": {"deal-new"}}),
        ]
        self.assertEqual(MODULE.select_variants(history, 2), {"deal-old"})

    def test_manifests_pin_source_hashes_and_caveats(self) -> None:
        historical = json.loads((DEAL_RELEASE / "manifest.json").read_text())
        identity = json.loads((IDENTITY_RELEASE / "manifest.json").read_text())
        plan = next(item for item in historical["artifacts"] if item["path"].startswith("source/"))
        registry = identity["artifacts"][0]
        self.assertEqual(plan["rows"], 6225)
        self.assertEqual(plan["sha256"], MODULE.EXPECTED_PLAN_SHA256)
        self.assertEqual(registry["rows"], 3725)
        self.assertEqual(registry["sha256"], MODULE.EXPECTED_REGISTRY_SHA256)
        self.assertIn("pending rights review", historical["license_caveat"])
        self.assertIn("client bundles", identity["privacy_caveat"])


if __name__ == "__main__":
    unittest.main()
