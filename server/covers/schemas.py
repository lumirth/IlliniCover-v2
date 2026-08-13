import uuid
from datetime import date, datetime
from typing import Literal

from config.schemas import CamelSchema
from pydantic import Field
from venues.schemas import VenueSummarySchema


class VenueDealSummarySchema(CamelSchema):
    id: uuid.UUID
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
    prediction_id: uuid.UUID | None


class CoverPriceSchema(CamelSchema):
    kind: str
    amount_cents: int | None = None
    low_cents: int | None = None
    high_cents: int | None = None


class CoverStateSchema(CamelSchema):
    price: CoverPriceSchema
    source: str
    freshness_seconds: int
    decision_id: uuid.UUID
    status: str


class VibeSummarySchema(CamelSchema):
    line_length: str | None = None
    line_speed: str | None = None
    crowd_level: str | None = None


class CoverVenueCardSchema(CamelSchema):
    venue: VenueSummarySchema
    cover: CoverStateSchema | None
    recent_report_count: int
    latest_activity_at: datetime | None
    vibes: VibeSummarySchema


class CoverBoardSchema(CamelSchema):
    service_date: date
    generated_at: datetime
    server_revision: str
    venues: list[CoverVenueCardSchema]


class RecentReportSchema(CamelSchema):
    submission_id: uuid.UUID
    observed_at: datetime
    received_at: datetime
    price_cents: int | None
    interaction: str
    broad_context: str | None
    vibes: list[str]


class VenueCoverDetailSchema(CamelSchema):
    venue: VenueSummarySchema
    cover: CoverStateSchema | None
    recent_reports: list[RecentReportSchema]
    vibes: VibeSummarySchema
    deals: list[VenueDealSummarySchema]


class CoverHistorySchema(CamelSchema):
    venue: VenueSummarySchema
    service_date: date
    access_tier: Literal["limited", "extended"]
    window_start: datetime
    has_more: bool = Field(
        description=(
            "True when additional admitted reports inside the applied history window were "
            "omitted by the tier's result cap."
        )
    )
    reports: list[RecentReportSchema]


class TimeMachineQuerySchema(CamelSchema):
    target_time: datetime


class TimeMachineSchema(CamelSchema):
    venue: VenueSummarySchema
    mode: Literal["past", "current", "future"]
    target_time: datetime
    knowledge_cutoff: datetime
    cover: CoverStateSchema | None
