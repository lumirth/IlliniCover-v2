from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime

from .receipts import JsonValue, canonical_receipt_hash
from .service_night import service_date_for, service_minute
from .types import HistoricalObservation, HistoricalPrediction


@dataclass(frozen=True, slots=True)
class HistoricalModelConfig:
    release_id: str = "cover_historical_v1"
    time_bandwidth_minutes: float = 60.0
    weekday_mismatch_weight: float = 0.08
    venue_pooling_strength: float = 8.0
    use_venue_effect: bool = True
    lower_quantile: float = 0.15
    upper_quantile: float = 0.85
    high_cover_threshold_cents: int = 2_000

    def __post_init__(self) -> None:
        if self.time_bandwidth_minutes <= 0:
            raise ValueError("time bandwidth must be positive")
        if not 0 <= self.weekday_mismatch_weight <= 1:
            raise ValueError("weekday mismatch weight must be between zero and one")
        if self.venue_pooling_strength < 0:
            raise ValueError("venue pooling strength cannot be negative")
        if not 0 <= self.lower_quantile <= self.upper_quantile <= 1:
            raise ValueError("historical interval quantiles are invalid")


DEFAULT_HISTORICAL_CONFIG = HistoricalModelConfig()


class HistoricalModel:
    """A deterministic continuous-time kernel with venue partial pooling.

    The fitted object retains admitted training rows so a release can be reproduced.
    Eligibility is evaluated against the caller's explicit knowledge cutoff; this
    makes accidental future leakage difficult in backtests and as-of debugging.
    """

    def __init__(
        self,
        observations: Iterable[HistoricalObservation],
        config: HistoricalModelConfig = DEFAULT_HISTORICAL_CONFIG,
    ) -> None:
        records = tuple(
            sorted(observations, key=lambda row: (row.available_at, row.observation_id))
        )
        if any(row.price_cents < 0 for row in records):
            raise ValueError("historical cover prices cannot be negative")
        if any(row.weight <= 0 for row in records):
            raise ValueError("historical observation weights must be positive")
        self._observations = records
        self.config = config

    @classmethod
    def fit(
        cls,
        observations: Iterable[HistoricalObservation],
        config: HistoricalModelConfig = DEFAULT_HISTORICAL_CONFIG,
    ) -> HistoricalModel:
        return cls(observations, config)

    @property
    def observation_count(self) -> int:
        return len(self._observations)

    def predict(
        self,
        venue_id: str,
        target_time: datetime,
        knowledge_cutoff: datetime,
    ) -> HistoricalPrediction | None:
        target_service_date = service_date_for(target_time)
        cutoff_service_date = service_date_for(knowledge_cutoff)
        target_minute = service_minute(target_time)
        target_weekday = target_service_date.weekday()
        venue_mass: dict[int, float] = {}
        campus_mass: dict[int, float] = {}
        venue_support = 0.0
        campus_support = 0.0

        for row in self._observations:
            if row.available_at > knowledge_cutoff:
                break
            if row.observed_at > knowledge_cutoff:
                continue
            # Long-term training admits only service nights completed before cutoff.
            if row.service_date >= cutoff_service_date:
                continue
            minute_delta = abs(service_minute(row.observed_at) - target_minute)
            time_weight = math.exp(-0.5 * (minute_delta / self.config.time_bandwidth_minutes) ** 2)
            weekday_weight = (
                1.0
                if row.service_date.weekday() == target_weekday
                else self.config.weekday_mismatch_weight
            )
            weight = row.weight * time_weight * weekday_weight
            if weight < 1e-12:
                continue
            campus_mass[row.price_cents] = campus_mass.get(row.price_cents, 0.0) + weight
            campus_support += weight
            if row.venue_id == venue_id:
                venue_mass[row.price_cents] = venue_mass.get(row.price_cents, 0.0) + weight
                venue_support += weight

        if not campus_mass:
            return None
        campus_distribution = _normalize(campus_mass)
        if self.config.use_venue_effect and venue_mass:
            venue_distribution = _normalize(venue_mass)
            alpha = venue_support / (venue_support + self.config.venue_pooling_strength)
            prices = set(campus_distribution) | set(venue_distribution)
            distribution = {
                price: alpha * venue_distribution.get(price, 0.0)
                + (1.0 - alpha) * campus_distribution.get(price, 0.0)
                for price in prices
            }
            reason = "venue_partial_pooling"
        else:
            alpha = 0.0
            distribution = campus_distribution
            reason = "campus_fallback"
        distribution = _normalize(distribution)
        point = _weighted_quantile(distribution, 0.5)
        low = _weighted_quantile(distribution, self.config.lower_quantile)
        high = _weighted_quantile(distribution, self.config.upper_quantile)
        return HistoricalPrediction(
            point_cents=point,
            low_cents=low,
            high_cents=high,
            probability_zero=distribution.get(0, 0.0),
            probability_high=sum(
                probability
                for price, probability in distribution.items()
                if price >= self.config.high_cover_threshold_cents
            ),
            support=venue_support + (1.0 - alpha) * campus_support,
            model_release=self.config.release_id,
            probabilities=distribution,
            reasons=(reason, "continuous_service_time", "completed_nights_only"),
        )

    def to_artifact(self) -> JsonValue:
        return {
            "artifact_schema": "cover_historical_kernel_v1",
            "config": asdict(self.config),
            "observations": [
                {
                    "observation_id": row.observation_id,
                    "venue_id": row.venue_id,
                    "observed_at": row.observed_at.isoformat(),
                    "available_at": row.available_at.isoformat(),
                    "service_date": row.service_date.isoformat(),
                    "price_cents": row.price_cents,
                    "weight": row.weight,
                }
                for row in self._observations
            ],
        }

    def artifact_sha256(self) -> str:
        return canonical_receipt_hash(self.to_artifact())

    @classmethod
    def from_artifact(cls, artifact: Mapping[str, object]) -> HistoricalModel:
        if artifact.get("artifact_schema") != "cover_historical_kernel_v1":
            raise ValueError("unsupported historical cover artifact")
        raw_config = artifact.get("config")
        raw_observations = artifact.get("observations")
        if not isinstance(raw_config, Mapping) or not isinstance(raw_observations, list):
            raise ValueError("invalid historical cover artifact")
        config = HistoricalModelConfig(**dict(raw_config))
        observations: list[HistoricalObservation] = []
        for value in raw_observations:
            if not isinstance(value, Mapping):
                raise ValueError("invalid historical observation artifact row")
            observations.append(
                HistoricalObservation(
                    observation_id=str(value["observation_id"]),
                    venue_id=str(value["venue_id"]),
                    observed_at=datetime.fromisoformat(str(value["observed_at"])),
                    available_at=datetime.fromisoformat(str(value["available_at"])),
                    service_date=date.fromisoformat(str(value["service_date"])),
                    price_cents=int(value["price_cents"]),
                    weight=float(value["weight"]),
                )
            )
        return cls(observations, config)


def _normalize(mass: Mapping[int, float]) -> dict[int, float]:
    total = sum(mass.values())
    if total <= 0:
        raise ValueError("cannot normalize empty probability mass")
    return {price: weight / total for price, weight in mass.items() if weight > 0}


def _weighted_quantile(distribution: Mapping[int, float], quantile: float) -> int:
    cumulative = 0.0
    values = sorted(distribution.items())
    for price, probability in values:
        cumulative += probability
        if cumulative >= quantile:
            return price
    return values[-1][0]
