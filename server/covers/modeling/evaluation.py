from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

from .historical import HistoricalModel, HistoricalModelConfig
from .nowcast import DEFAULT_NOWCAST_CONFIG, NowcastConfig, compute_nowcast
from .service_night import CHICAGO
from .types import HistoricalObservation, HistoricalPrediction, ObservationInput


@dataclass(frozen=True, slots=True)
class MetricSummary:
    observations: int
    mae_cents: float
    rmse_cents: float
    zero_brier: float
    high_cover_brier: float
    interval_coverage: float
    mean_interval_width_cents: float
    mean_interval_score_cents: float

    def as_dict(self) -> dict[str, int | float]:
        return {
            "observations": self.observations,
            "mae_cents": round(self.mae_cents, 6),
            "rmse_cents": round(self.rmse_cents, 6),
            "zero_brier": round(self.zero_brier, 9),
            "high_cover_brier": round(self.high_cover_brier, 9),
            "interval_coverage": round(self.interval_coverage, 9),
            "mean_interval_width_cents": round(self.mean_interval_width_cents, 6),
            "mean_interval_score_cents": round(self.mean_interval_score_cents, 6),
        }


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    metrics: MetricSummary
    venue_slices: Mapping[str, MetricSummary]
    time_slices: Mapping[str, MetricSummary]

    def as_dict(self) -> dict[str, object]:
        return {
            "metrics": self.metrics.as_dict(),
            "venue_slices": {
                key: value.as_dict() for key, value in sorted(self.venue_slices.items())
            },
            "time_slices": {
                key: value.as_dict() for key, value in sorted(self.time_slices.items())
            },
        }


@dataclass(frozen=True, slots=True)
class ChallengerPromotionPolicy:
    protocol_version: str = "chronological_holdout_v1"
    minimum_service_nights: int = 4
    minimum_common_observations: int = 20
    maximum_mae_cents: int = 800
    minimum_interval_coverage: float = 0.70
    maximum_mean_interval_width_cents: int = 2_000
    maximum_venue_mae_cents: int = 1_000


DEFAULT_CHALLENGER_PROMOTION_POLICY = ChallengerPromotionPolicy()


@dataclass(frozen=True, slots=True)
class _ScoredPrediction:
    actual_cents: int
    prediction: HistoricalPrediction


def load_recovered_release(path: Path) -> tuple[HistoricalObservation, ...]:
    observations: list[HistoricalObservation] = []
    with path.open() as source:
        for line in source:
            value = json.loads(line)
            observations.append(
                HistoricalObservation(
                    observation_id=value["source_record_key"],
                    venue_id=value["venue_slug"],
                    observed_at=_parse_datetime(value["observed_at"]),
                    available_at=_parse_datetime(value["firestore_create_time"]),
                    service_date=date.fromisoformat(value["service_date"]),
                    price_cents=int(value["reported_price_cents"]),
                )
            )
    return tuple(observations)


def default_historical_candidates() -> tuple[HistoricalModelConfig, ...]:
    return (
        HistoricalModelConfig(
            release_id="campus_weekday_time_120",
            time_bandwidth_minutes=120,
            use_venue_effect=False,
        ),
        HistoricalModelConfig(
            release_id="venue_pool_weekday_time_60",
            time_bandwidth_minutes=60,
            venue_pooling_strength=8,
        ),
        HistoricalModelConfig(
            release_id="venue_pool_weekday_time_90",
            time_bandwidth_minutes=90,
            venue_pooling_strength=8,
        ),
        HistoricalModelConfig(
            release_id="venue_pool_weekday_time_120",
            time_bandwidth_minutes=120,
            venue_pooling_strength=8,
        ),
    )


def chronological_model_selection(
    observations: Sequence[HistoricalObservation],
    *,
    candidates: Sequence[HistoricalModelConfig] | None = None,
    holdout_fraction: float = 0.15,
    minimum_selection_history_fraction: float = 0.45,
) -> dict[str, object]:
    """Select on older folds, then open the newest untouched service-date holdout."""

    if not 0 < holdout_fraction < 0.5:
        raise ValueError("holdout fraction must be between zero and one half")
    candidates = candidates or default_historical_candidates()
    service_dates = sorted({row.service_date for row in observations})
    holdout_index = max(
        1, min(len(service_dates) - 1, math.floor(len(service_dates) * (1.0 - holdout_fraction)))
    )
    holdout_start = service_dates[holdout_index]
    selection_dates = service_dates[:holdout_index]
    selection_start_index = max(
        1, math.floor(len(selection_dates) * minimum_selection_history_fraction)
    )
    selection_start = selection_dates[selection_start_index]
    selection_rows = tuple(
        row for row in observations if selection_start <= row.service_date < holdout_start
    )
    holdout_rows = tuple(row for row in observations if row.service_date >= holdout_start)
    if not selection_rows or not holdout_rows:
        raise ValueError("chronological split produced an empty evaluation partition")

    candidate_results: dict[str, EvaluationResult] = {}
    models: dict[str, HistoricalModel] = {}
    for config in candidates:
        model = HistoricalModel.fit(observations, config)
        models[config.release_id] = model
        candidate_results[config.release_id] = evaluate_model(model, selection_rows)
    selected_id = min(
        candidate_results,
        key=lambda key: (
            candidate_results[key].metrics.mae_cents,
            candidate_results[key].metrics.mean_interval_score_cents,
            candidate_results[key].metrics.zero_brier,
            key,
        ),
    )
    selected_model = models[selected_id]
    final_result = evaluate_model(selected_model, holdout_rows)
    nowcast_result = evaluate_nowcast(selected_model, observations, holdout_rows)
    return {
        "evaluation_schema": "cover_chronological_selection_v1",
        "selection_policy": {
            "primary": "selection MAE",
            "tie_breakers": ["interval score", "zero-cover Brier", "release id"],
            "random_split_used": False,
            "service_date_partitioned": True,
        },
        "partitions": {
            "all_service_dates": len(service_dates),
            "selection_start": selection_start.isoformat(),
            "selection_end_exclusive": holdout_start.isoformat(),
            "selection_rolling_origin_service_dates": len(
                {row.service_date for row in selection_rows}
            ),
            "selection_observations": len(selection_rows),
            "holdout_start": holdout_start.isoformat(),
            "holdout_end": service_dates[-1].isoformat(),
            "holdout_service_dates": len({row.service_date for row in holdout_rows}),
            "holdout_observations": len(holdout_rows),
        },
        "candidates": {
            config.release_id: {
                "config": asdict(config),
                "selection": candidate_results[config.release_id].as_dict(),
            }
            for config in candidates
        },
        "selected_release": selected_id,
        "final_untouched_holdout": final_result.as_dict(),
        "final_holdout_nowcast_ablation": nowcast_result,
    }


def evaluate_model(
    model: HistoricalModel, observations: Iterable[HistoricalObservation]
) -> EvaluationResult:
    scored: list[_ScoredPrediction] = []
    venue: dict[str, list[_ScoredPrediction]] = defaultdict(list)
    time: dict[str, list[_ScoredPrediction]] = defaultdict(list)
    for row in sorted(observations, key=lambda value: (value.observed_at, value.observation_id)):
        prediction = model.predict(row.venue_id, row.observed_at, knowledge_cutoff=row.observed_at)
        if prediction is None:
            continue
        value = _ScoredPrediction(row.price_cents, prediction)
        scored.append(value)
        venue[row.venue_id].append(value)
        time[_time_slice(row.observed_at)].append(value)
    return EvaluationResult(
        metrics=_metrics(scored, model.config),
        venue_slices={key: _metrics(values, model.config) for key, values in venue.items()},
        time_slices={key: _metrics(values, model.config) for key, values in time.items()},
    )


def compare_historical_models(
    incumbent: HistoricalModel,
    challenger: HistoricalModel,
    observations: Iterable[HistoricalObservation],
    *,
    policy: ChallengerPromotionPolicy = DEFAULT_CHALLENGER_PROMOTION_POLICY,
) -> dict[str, object]:
    """Compare fixed releases on one shared chronological holdout population."""

    incumbent_scored: list[_ScoredPrediction] = []
    challenger_scored: list[_ScoredPrediction] = []
    incumbent_by_venue: dict[str, list[_ScoredPrediction]] = defaultdict(list)
    challenger_by_venue: dict[str, list[_ScoredPrediction]] = defaultdict(list)
    incumbent_by_time: dict[str, list[_ScoredPrediction]] = defaultdict(list)
    challenger_by_time: dict[str, list[_ScoredPrediction]] = defaultdict(list)
    common_rows: list[HistoricalObservation] = []

    for row in sorted(
        observations,
        key=lambda value: (value.observed_at, value.available_at, value.observation_id),
    ):
        incumbent_prediction = incumbent.predict(
            row.venue_id,
            row.observed_at,
            knowledge_cutoff=row.observed_at,
        )
        challenger_prediction = challenger.predict(
            row.venue_id,
            row.observed_at,
            knowledge_cutoff=row.observed_at,
        )
        if incumbent_prediction is None or challenger_prediction is None:
            continue
        common_rows.append(row)
        incumbent_value = _ScoredPrediction(row.price_cents, incumbent_prediction)
        challenger_value = _ScoredPrediction(row.price_cents, challenger_prediction)
        incumbent_scored.append(incumbent_value)
        challenger_scored.append(challenger_value)
        incumbent_by_venue[row.venue_id].append(incumbent_value)
        challenger_by_venue[row.venue_id].append(challenger_value)
        time_slice = _time_slice(row.observed_at)
        incumbent_by_time[time_slice].append(incumbent_value)
        challenger_by_time[time_slice].append(challenger_value)

    incumbent_result = EvaluationResult(
        metrics=_metrics(incumbent_scored, incumbent.config),
        venue_slices={
            key: _metrics(values, incumbent.config)
            for key, values in incumbent_by_venue.items()
        },
        time_slices={
            key: _metrics(values, incumbent.config) for key, values in incumbent_by_time.items()
        },
    )
    challenger_result = EvaluationResult(
        metrics=_metrics(challenger_scored, challenger.config),
        venue_slices={
            key: _metrics(values, challenger.config)
            for key, values in challenger_by_venue.items()
        },
        time_slices={
            key: _metrics(values, challenger.config)
            for key, values in challenger_by_time.items()
        },
    )
    incumbent_metrics = incumbent_result.metrics
    challenger_metrics = challenger_result.metrics
    comparative_gates = {
        "mae_strictly_improved": challenger_metrics.mae_cents < incumbent_metrics.mae_cents,
        "zero_brier_non_regression": (
            challenger_metrics.zero_brier <= incumbent_metrics.zero_brier
        ),
        "high_cover_brier_non_regression": (
            challenger_metrics.high_cover_brier <= incumbent_metrics.high_cover_brier
        ),
        "interval_score_non_regression": (
            challenger_metrics.mean_interval_score_cents
            <= incumbent_metrics.mean_interval_score_cents
        ),
    }
    sample_gates = {
        "minimum_service_nights": (
            len({row.service_date for row in common_rows}) >= policy.minimum_service_nights
        ),
        "minimum_common_observations": (
            len(common_rows) >= policy.minimum_common_observations
        ),
    }
    absolute_gates = {
        "absolute_mae": challenger_metrics.mae_cents <= policy.maximum_mae_cents,
        "absolute_interval_coverage": (
            challenger_metrics.interval_coverage >= policy.minimum_interval_coverage
        ),
        "absolute_interval_width": (
            challenger_metrics.mean_interval_width_cents
            <= policy.maximum_mean_interval_width_cents
        ),
        "absolute_venue_mae": bool(challenger_result.venue_slices)
        and all(
            metrics.mae_cents <= policy.maximum_venue_mae_cents
            for metrics in challenger_result.venue_slices.values()
        ),
    }
    gates = {**sample_gates, **comparative_gates, **absolute_gates}
    challenger_won = all(comparative_gates.values())

    return {
        "protocol_version": policy.protocol_version,
        "policy": asdict(policy),
        "sample": {
            "common_observations": len(common_rows),
            "service_nights": len({row.service_date for row in common_rows}),
            "venues": len({row.venue_id for row in common_rows}),
        },
        "incumbent": incumbent_result.as_dict(),
        "challenger": challenger_result.as_dict(),
        "comparison": {
            "mae_delta_cents": round(
                challenger_metrics.mae_cents - incumbent_metrics.mae_cents, 6
            ),
            "zero_brier_delta": round(
                challenger_metrics.zero_brier - incumbent_metrics.zero_brier, 9
            ),
            "high_cover_brier_delta": round(
                challenger_metrics.high_cover_brier - incumbent_metrics.high_cover_brier, 9
            ),
            "mean_interval_score_delta_cents": round(
                challenger_metrics.mean_interval_score_cents
                - incumbent_metrics.mean_interval_score_cents,
                6,
            ),
        },
        "gates": gates,
        "challenger_won": challenger_won,
        "promotion_eligible": challenger_won and all(gates.values()),
        "not_evaluable_dimensions": {
            "campus_adjustment_ablation": "historical release comparison only",
            "context_feature_ablation": "no versioned context labels in evaluation rows",
            "post_launch_shadow_performance": "no matched outcome receipt contract",
            "same_night_nowcast_value": "historical release comparison only",
            "sparse_data_performance": "no frozen sparse-support slice definition",
            "special_event_slices": "no versioned context labels in evaluation rows",
        },
    }


def evaluate_nowcast(
    model: HistoricalModel,
    all_observations: Sequence[HistoricalObservation],
    evaluation_observations: Sequence[HistoricalObservation],
    *,
    config: NowcastConfig = DEFAULT_NOWCAST_CONFIG,
) -> dict[str, object]:
    by_service_date: dict[date, list[HistoricalObservation]] = defaultdict(list)
    for row in all_observations:
        by_service_date[row.service_date].append(row)
    baseline_errors: list[float] = []
    venue_errors: list[float] = []
    full_errors: list[float] = []
    campus_eligible = 0
    changed_predictions = 0

    def lookup(
        venue_id: str, target_time: datetime, cutoff: datetime
    ) -> HistoricalPrediction | None:
        return model.predict(venue_id, target_time, knowledge_cutoff=cutoff)

    for target in sorted(
        evaluation_observations, key=lambda value: (value.observed_at, value.observation_id)
    ):
        prior = [
            row
            for row in by_service_date[target.service_date]
            if row.observed_at < target.observed_at and row.available_at <= target.observed_at
        ]
        if not any(row.venue_id == target.venue_id for row in prior):
            continue
        baseline = model.predict(
            target.venue_id, target.observed_at, knowledge_cutoff=target.observed_at
        )
        if baseline is None:
            continue
        inputs = tuple(_as_live_observation(row) for row in prior)
        adjustment = compute_nowcast(
            target_venue_id=target.venue_id,
            target_time=target.observed_at,
            knowledge_cutoff=target.observed_at,
            observations=inputs,
            historical_lookup=lookup,
            config=config,
        )
        venue_prediction = _snap_cover(baseline.point_cents + adjustment.venue_delta_cents)
        full_prediction = _snap_cover(baseline.point_cents + adjustment.total_delta_cents)
        baseline_errors.append(abs(target.price_cents - baseline.point_cents))
        venue_errors.append(abs(target.price_cents - venue_prediction))
        full_errors.append(abs(target.price_cents - full_prediction))
        if adjustment.campus_venue_count >= config.minimum_campus_venues:
            campus_eligible += 1
        if full_prediction != baseline.point_cents:
            changed_predictions += 1
    return {
        "observations": len(baseline_errors),
        "baseline_mae_cents": _mean(baseline_errors),
        "venue_nowcast_mae_cents": _mean(venue_errors),
        "venue_plus_campus_nowcast_mae_cents": _mean(full_errors),
        "campus_eligible_observations": campus_eligible,
        "changed_predictions": changed_predictions,
        "config": asdict(config),
        "caveat": (
            "Recovered rows have no actor or trust provenance; each source record is treated "
            "as independent only for this limited sequential ablation."
        ),
    }


def release_evaluation(
    dataset_path: Path,
    *,
    candidates: Sequence[HistoricalModelConfig] | None = None,
) -> dict[str, object]:
    observations = load_recovered_release(dataset_path)
    result = chronological_model_selection(observations, candidates=candidates)
    result["dataset"] = {
        "path": str(dataset_path),
        "sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "observations": len(observations),
        "venues": sorted({row.venue_id for row in observations}),
    }
    return result


def _metrics(values: Sequence[_ScoredPrediction], config: HistoricalModelConfig) -> MetricSummary:
    if not values:
        return MetricSummary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    errors = [value.prediction.point_cents - value.actual_cents for value in values]
    coverage = [
        value.prediction.low_cents <= value.actual_cents <= value.prediction.high_cents
        for value in values
    ]
    widths = [value.prediction.high_cents - value.prediction.low_cents for value in values]
    alpha = max(1e-9, 1.0 - (config.upper_quantile - config.lower_quantile))
    interval_scores = []
    for value, width in zip(values, widths, strict=True):
        penalty = 0.0
        if value.actual_cents < value.prediction.low_cents:
            penalty = 2.0 / alpha * (value.prediction.low_cents - value.actual_cents)
        elif value.actual_cents > value.prediction.high_cents:
            penalty = 2.0 / alpha * (value.actual_cents - value.prediction.high_cents)
        interval_scores.append(width + penalty)
    return MetricSummary(
        observations=len(values),
        mae_cents=_mean([abs(error) for error in errors]),
        rmse_cents=math.sqrt(_mean([error * error for error in errors])),
        zero_brier=_mean(
            [
                (value.prediction.probability_zero - float(value.actual_cents == 0)) ** 2
                for value in values
            ]
        ),
        high_cover_brier=_mean(
            [
                (
                    value.prediction.probability_high
                    - float(value.actual_cents >= config.high_cover_threshold_cents)
                )
                ** 2
                for value in values
            ]
        ),
        interval_coverage=_mean([float(item) for item in coverage]),
        mean_interval_width_cents=_mean(widths),
        mean_interval_score_cents=_mean(interval_scores),
    )


def _as_live_observation(row: HistoricalObservation) -> ObservationInput:
    return ObservationInput(
        observation_id=row.observation_id,
        venue_id=row.venue_id,
        actor_independence_key=row.observation_id,
        observed_at=row.observed_at,
        received_at=row.available_at,
        price_cents=row.price_cents,
    )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _time_slice(moment: datetime) -> str:
    hour = moment.astimezone(CHICAGO).hour
    if 5 <= hour < 20:
        return "before_20"
    if 20 <= hour < 22:
        return "20_to_22"
    if hour >= 22:
        return "22_to_midnight"
    return "after_midnight"


def _snap_cover(value: int) -> int:
    return max(0, int(round(value / 500.0) * 500))


def _mean(values: Sequence[float | int]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 6)
