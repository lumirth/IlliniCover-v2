import uuid
from datetime import date, datetime
from typing import Literal

from config.schemas import CamelSchema
from pydantic import Field, model_validator
from submissions.schemas import LocationInputSchema
from venues.schemas import VenueSummarySchema

from deals.names import public_deal_name


class DealShapeSchema(CamelSchema):
    display_name: str = Field(min_length=1, max_length=180)
    category: Literal["drink", "food"]
    canonical_family_id: uuid.UUID | None = None
    price_kind: Literal["absolute", "single", "range", "relative", "percent_off", "unknown"]
    price_cents: int | None = Field(default=None, ge=0, le=25_000)
    price_low_cents: int | None = Field(default=None, ge=0, le=25_000)
    price_high_cents: int | None = Field(default=None, ge=0, le=25_000)
    discount_percent: float | None = Field(default=None, gt=0, le=100)
    unit: str = Field(default="", max_length=80)
    serving_format: str = Field(default="", max_length=120)
    timing_description: str = Field(default="", max_length=160)
    timing_known: bool = False
    while_supplies_last: bool = False

    @model_validator(mode="after")
    def coherent_shape(self):
        self.unit = self.unit.strip()
        self.serving_format = self.serving_format.strip()
        self.timing_description = self.timing_description.strip()
        single = self.price_kind in {"absolute", "single"}
        relative = self.price_kind in {"relative", "percent_off"}
        if single and (
            self.price_cents is None
            or self.price_low_cents is not None
            or self.price_high_cents is not None
            or self.discount_percent is not None
        ):
            raise ValueError("single price requires only priceCents")
        if self.price_kind == "range" and (
            self.price_low_cents is None
            or self.price_high_cents is None
            or self.price_low_cents > self.price_high_cents
            or self.price_cents is not None
            or self.discount_percent is not None
        ):
            raise ValueError("range requires ordered low/high prices only")
        if relative and (
            self.discount_percent is None
            or self.price_cents is not None
            or self.price_low_cents is not None
            or self.price_high_cents is not None
        ):
            raise ValueError("relative price requires only discountPercent")
        if self.price_kind == "unknown" and any(
            value is not None
            for value in (
                self.price_cents,
                self.price_low_cents,
                self.price_high_cents,
                self.discount_percent,
            )
        ):
            raise ValueError("unknown price cannot include a price value")
        has_description = bool(self.timing_description)
        if not self.timing_known and (has_description or self.while_supplies_last):
            raise ValueError("unknown timing cannot include timing claims")
        self.display_name = public_deal_name(
            self.display_name,
            price_kind=self.price_kind,
            price_cents=self.price_cents,
            price_low_cents=self.price_low_cents,
            price_high_cents=self.price_high_cents,
            discount_percent=self.discount_percent,
        )
        if not self.display_name:
            raise ValueError("displayName must include a product name, not only a price")
        return self


class DealEvidenceInputSchema(CamelSchema):
    submission_id: uuid.UUID
    venue_id: uuid.UUID
    observed_at: datetime
    action: Literal["ADD_MISSING", "CONFIRM_PRESENT", "DENY_PRESENT", "CORRECT"]
    target_deal_id: uuid.UUID | None = None
    submitted_deal_shape: DealShapeSchema | None = None
    service_date_local: date
    vantage_point: Literal["outside", "inside", "unknown"] = "unknown"
    location: LocationInputSchema | None = None
    client_platform: str = Field(default="ios", max_length=24)
    entry_point: str = Field(default="", max_length=40)

    @model_validator(mode="after")
    def action_has_required_evidence(self):
        if self.observed_at.tzinfo is None:
            raise ValueError("observedAt must include a timezone")
        if bool(self.submitted_deal_shape) != (self.action in {"ADD_MISSING", "CORRECT"}):
            raise ValueError("only add and correct require a submitted deal shape")
        if bool(self.target_deal_id) != (self.action != "ADD_MISSING"):
            raise ValueError("only add has no target deal")
        return self


class DealEvidenceReceiptSchema(CamelSchema):
    submission_id: uuid.UUID
    accepted_at: datetime
    duplicate: bool


class DealSchema(CamelSchema):
    id: uuid.UUID
    canonical_family_id: uuid.UUID
    display_name: str
    category: str
    price_kind: str
    price_cents: int | None
    price_low_cents: int | None
    price_high_cents: int | None
    discount_percent: float | None
    unit: str
    serving_format: str
    timing_description: str | None
    timing_known: bool
    while_supplies_last: bool
    status: str
    latest_activity_at: datetime | None = None


class VenueDealsSchema(CamelSchema):
    venue: VenueSummarySchema
    deals: list[DealSchema]


class DealSlateSchema(CamelSchema):
    service_date: date
    generated_at: datetime
    venues: list[VenueDealsSchema]


class DealSuggestionSchema(CamelSchema):
    canonical_family_id: uuid.UUID
    category: str
    display_name: str
    price_kind: str
    price_cents: int | None
    price_low_cents: int | None = None
    price_high_cents: int | None = None
    discount_percent: float | None
    unit: str
    serving_format: str
    timing_description: str | None
    timing_known: bool
    while_supplies_last: bool
    source_scope: str
    last_seen_service_date_local: date


class DealSuggestionsSchema(CamelSchema):
    suggestions: list[DealSuggestionSchema]
