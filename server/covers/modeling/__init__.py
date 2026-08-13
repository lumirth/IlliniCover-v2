"""Pure cover interpretation for IlliniCover v2.

This package deliberately has no Django dependency. ORM-facing code converts durable
observations into these immutable inputs, then persists the returned receipt fields.
"""

from .historical import HistoricalModel, HistoricalModelConfig
from .nowcast import NowcastConfig, compute_nowcast
from .resolver import ResolverConfig, resolve_cover
from .time_machine import ReconstructionConfig, cover_at, reconstruct_cover
from .trust import TrustPolicy, assess_observation
from .types import (
    AdmissionClass,
    AdvertisedAdmissionInput,
    CoverResolution,
    HistoricalObservation,
    HistoricalPrediction,
    LocationContext,
    NowcastAdjustment,
    ObservationInput,
)

__all__ = [
    "AdmissionClass",
    "AdvertisedAdmissionInput",
    "CoverResolution",
    "HistoricalModel",
    "HistoricalModelConfig",
    "HistoricalObservation",
    "HistoricalPrediction",
    "LocationContext",
    "NowcastAdjustment",
    "NowcastConfig",
    "ObservationInput",
    "ReconstructionConfig",
    "ResolverConfig",
    "TrustPolicy",
    "assess_observation",
    "compute_nowcast",
    "cover_at",
    "reconstruct_cover",
    "resolve_cover",
]
