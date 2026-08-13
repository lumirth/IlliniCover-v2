from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from covers.modeling.evaluation import (
    DEFAULT_CHALLENGER_PROMOTION_POLICY,
    compare_historical_models,
    release_evaluation,
)
from covers.modeling.historical import HistoricalModel, HistoricalModelConfig
from covers.modeling.receipts import canonical_receipt_hash
from covers.modeling.types import HistoricalObservation

DATASET = Path("data/cover/recovered-cover-v1/cover-observations-v1.jsonl")


def test_recovered_release_chronological_selection_is_reproducible():
    result = release_evaluation(DATASET)
    assert canonical_receipt_hash(result) == (
        "6f2ab9fa650e095b46798837a0c51aaf0ffed3a7a9b7e466648786980525cc72"
    )
    assert result["dataset"]["sha256"] == (
        "aaab73ccf1a825e1192f04ff00a0affcf0fb877da3d744ed3a6c33d60ed8674e"
    )
    assert result["selected_release"] == "venue_pool_weekday_time_60"
    selection = result["candidates"]["venue_pool_weekday_time_60"]["selection"]["metrics"]
    holdout = result["final_untouched_holdout"]["metrics"]
    nowcast = result["final_holdout_nowcast_ablation"]
    assert selection["mae_cents"] == pytest.approx(624.283305)
    assert holdout["mae_cents"] == pytest.approx(750.0)
    assert holdout["interval_coverage"] == pytest.approx(0.792308, abs=1e-9)
    assert nowcast["venue_plus_campus_nowcast_mae_cents"] == pytest.approx(760.416667)
    assert nowcast["venue_plus_campus_nowcast_mae_cents"] < nowcast["baseline_mae_cents"]
    assert all(
        venue["mae_cents"] <= 1_000
        for venue in result["final_untouched_holdout"]["venue_slices"].values()
    )


def test_challenger_comparison_promotes_only_on_one_common_chronological_population():
    training_time = datetime(2026, 1, 1, 12, tzinfo=UTC)
    incumbent = HistoricalModel.fit(
        [
            HistoricalObservation(
                observation_id="incumbent-training",
                venue_id="venue-0",
                observed_at=training_time - timedelta(days=7),
                available_at=training_time - timedelta(days=7),
                service_date=date(2025, 12, 25),
                price_cents=1_000,
            )
        ],
        HistoricalModelConfig(release_id="incumbent", use_venue_effect=False),
    )
    challenger = HistoricalModel.fit(
        [
            HistoricalObservation(
                observation_id="challenger-training",
                venue_id="venue-0",
                observed_at=training_time - timedelta(days=7),
                available_at=training_time - timedelta(days=7),
                service_date=date(2025, 12, 25),
                price_cents=1_500,
            )
        ],
        HistoricalModelConfig(release_id="challenger", use_venue_effect=False),
    )
    holdout = tuple(
        HistoricalObservation(
            observation_id=f"held-out-{index}",
            venue_id=f"venue-{index % 4}",
            observed_at=training_time + timedelta(days=index // 5 + 1),
            available_at=training_time + timedelta(days=index // 5 + 1, minutes=1),
            service_date=date(2026, 1, 2) + timedelta(days=index // 5),
            price_cents=1_500,
        )
        for index in range(20)
    )

    result = compare_historical_models(
        incumbent,
        challenger,
        holdout,
        policy=DEFAULT_CHALLENGER_PROMOTION_POLICY,
    )

    assert result["sample"] == {
        "common_observations": 20,
        "service_nights": 4,
        "venues": 4,
    }
    assert result["comparison"]["mae_delta_cents"] == -500.0
    assert result["gates"] == {
        "minimum_service_nights": True,
        "minimum_common_observations": True,
        "mae_strictly_improved": True,
        "zero_brier_non_regression": True,
        "high_cover_brier_non_regression": True,
        "interval_score_non_regression": True,
        "absolute_mae": True,
        "absolute_interval_coverage": True,
        "absolute_interval_width": True,
        "absolute_venue_mae": True,
    }
    assert result["challenger_won"] is True
    assert result["promotion_eligible"] is True
    assert result["not_evaluable_dimensions"] == {
        "campus_adjustment_ablation": "historical release comparison only",
        "context_feature_ablation": "no versioned context labels in evaluation rows",
        "post_launch_shadow_performance": "no matched outcome receipt contract",
        "same_night_nowcast_value": "historical release comparison only",
        "sparse_data_performance": "no frozen sparse-support slice definition",
        "special_event_slices": "no versioned context labels in evaluation rows",
    }
