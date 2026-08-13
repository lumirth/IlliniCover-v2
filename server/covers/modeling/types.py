from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from types import MappingProxyType

from .receipts import JsonValue, canonical_receipt_hash


class AdmissionClass(StrEnum):
    NORMAL = "normal"
    REDUCED = "reduced"
    EXCLUDED = "excluded"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class LocationContext:
    """Privacy-minimized location input for evidence assessment.

    Exact coordinates remain in private persistence. The cover engine needs only the
    derived distance and reported accuracy for the current assessment.
    """

    distance_to_venue_m: float
    accuracy_m: float


@dataclass(frozen=True, slots=True)
class ObservationInput:
    observation_id: str
    venue_id: str
    actor_independence_key: str
    observed_at: datetime
    received_at: datetime
    price_cents: int
    interaction_kind: str = "direct"
    displayed_source: str | None = None
    displayed_price_cents: int | None = None
    price_prefilled: bool = False
    price_touched: bool = False
    time_quality: str = "good"
    location: LocationContext | None = None
    installation_age_days: float | None = None
    prior_corroborations: int = 0
    signed_in: bool = False
    hard_abuse: bool = False
    impossible_movement: bool = False
    rapid_spam: bool = False
    linked_account_stuffing: bool = False
    known_automation: bool = False
    severe_clock_manipulation: bool = False

    @property
    def is_untouched_historical_echo(self) -> bool:
        return (
            self.price_prefilled
            and not self.price_touched
            and self.displayed_source == "historical"
            and self.displayed_price_cents == self.price_cents
        )

    @property
    def is_manual_correction(self) -> bool:
        return (
            self.price_touched
            and self.displayed_price_cents is not None
            and self.displayed_price_cents != self.price_cents
        )


@dataclass(frozen=True, slots=True)
class AdvertisedAdmissionInput:
    """One validated, time-scoped direct admission fact.

    Only unconditional facts are allowed to become a universal displayed cover.
    Conditional facts remain preserved in the context tables but are deliberately
    excluded from this resolver input.
    """

    admission_id: str
    venue_id: str
    price_cents: int
    available_at: datetime
    starts_at: datetime
    ends_at: datetime | None
    is_unconditional: bool
    qualification: str = ""


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    observation_id: str
    admission: AdmissionClass
    weight: float
    independent_price_label: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HistoricalObservation:
    observation_id: str
    venue_id: str
    observed_at: datetime
    available_at: datetime
    service_date: date
    price_cents: int
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class HistoricalPrediction:
    point_cents: int
    low_cents: int
    high_cents: int
    probability_zero: float
    probability_high: float
    support: float
    model_release: str
    probabilities: Mapping[int, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "probabilities", MappingProxyType(dict(self.probabilities)))


@dataclass(frozen=True, slots=True)
class NowcastAdjustment:
    venue_delta_cents: int = 0
    campus_delta_cents: int = 0
    venue_support: float = 0.0
    campus_support: float = 0.0
    venue_observation_count: int = 0
    campus_venue_count: int = 0
    reasons: tuple[str, ...] = ()

    @property
    def total_delta_cents(self) -> int:
        return self.venue_delta_cents + self.campus_delta_cents


@dataclass(frozen=True, slots=True)
class CoverResolution:
    price_kind: str
    amount_cents: int | None
    low_cents: int | None
    high_cents: int | None
    source: str
    status: str
    freshness_seconds: int | None
    support: float
    reasons: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    model_release: str | None = None
    venue_adjustment_cents: int = 0
    campus_adjustment_cents: int = 0

    def receipt_summary(self) -> JsonValue:
        """Return JSON-safe, deliberately compact decision-receipt fields."""

        return {
            "price_kind": self.price_kind,
            "amount_cents": self.amount_cents,
            "low_cents": self.low_cents,
            "high_cents": self.high_cents,
            "source": self.source,
            "status": self.status,
            "freshness_seconds": self.freshness_seconds,
            "support": round(self.support, 6),
            "reasons": list(self.reasons),
            "evidence_ids": list(self.evidence_ids),
            "model_release": self.model_release,
            "venue_adjustment_cents": self.venue_adjustment_cents,
            "campus_adjustment_cents": self.campus_adjustment_cents,
        }

    def receipt_sha256(self) -> str:
        return canonical_receipt_hash(self.receipt_summary())
