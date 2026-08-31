import uuid
from datetime import datetime
from typing import Literal

from config.schemas import CamelSchema
from covers.schemas import CoverStateSchema
from pydantic import Field, model_validator


class LocationInputSchema(CamelSchema):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy_meters: float = Field(ge=0, le=999_999.99, allow_inf_nan=False)
    permission: Literal["when_in_use"] = "when_in_use"


class CoverInputSchema(CamelSchema):
    # A draft may contain an intermediate decimal while the person is typing,
    # but a committed cover report is always one of the product's $5 steps.
    # Historical imports intentionally bypass this client-write schema so their
    # raw legacy observations remain intact.
    price_cents: int = Field(ge=0, le=7_000, multiple_of=500)
    interaction: Literal["confirm", "correct", "direct", "quick_confirm", "manual"]
    price_prefilled: bool = False
    price_touched: bool = False
    displayed_source: str | None = None
    displayed_price_kind: str | None = None
    displayed_amount_cents: int | None = None
    displayed_low_cents: int | None = None
    displayed_high_cents: int | None = None


class VibeInputSchema(CamelSchema):
    dimension: Literal["line_length", "line_speed", "crowd_level"]
    value: str

    @model_validator(mode="after")
    def value_matches_dimension(self):
        values = {
            "line_length": {"short", "medium", "long"},
            "line_speed": {"slow", "normal", "fast"},
            "crowd_level": {"quiet", "busy", "packed"},
        }
        if self.value not in values[self.dimension]:
            raise ValueError("vibe value does not match its dimension")
        return self


class CoverSubmissionSchema(CamelSchema):
    submission_id: uuid.UUID
    venue_id: uuid.UUID
    observed_at: datetime
    vantage_point: Literal["outside", "inside", "unknown"] = "unknown"
    location: LocationInputSchema | None = None
    cover: CoverInputSchema | None = None
    vibes: list[VibeInputSchema] = Field(default_factory=list, max_length=3)
    client_platform: str = Field(default="ios", max_length=24)
    entry_point: str = Field(default="", max_length=40)

    @model_validator(mode="after")
    def contains_real_observation(self):
        if self.cover is None and not self.vibes:
            raise ValueError("at least one cover or vibe observation is required")
        dimensions = [vibe.dimension for vibe in self.vibes]
        if len(set(dimensions)) != len(dimensions):
            raise ValueError("each vibe dimension can appear only once")
        if self.observed_at.tzinfo is None:
            raise ValueError("observedAt must include a timezone")
        return self


class SubmissionReceiptSchema(CamelSchema):
    submission_id: uuid.UUID
    accepted_at: datetime
    duplicate: bool
    cover: CoverStateSchema | None
