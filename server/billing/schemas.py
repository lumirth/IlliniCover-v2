from datetime import datetime
from typing import Literal

from config.schemas import CamelSchema
from pydantic import Field


class EntitlementSchema(CamelSchema):
    identifier: Literal["premium"]
    is_active: bool
    expires_at: datetime | None
    updated_at: datetime | None


class EntitlementsSchema(CamelSchema):
    entitlements: list[EntitlementSchema]


class RevenueCatEventSchema(CamelSchema):
    id: str = Field(min_length=1, max_length=160)
    type: str = Field(min_length=1, max_length=80)
    app_user_id: str = Field(default="", max_length=160)
    original_app_user_id: str = Field(default="", max_length=160)
    aliases: list[str] = Field(default_factory=list)
    transferred_from: list[str] = Field(default_factory=list)
    transferred_to: list[str] = Field(default_factory=list)


class RevenueCatEnvelopeSchema(CamelSchema):
    event: RevenueCatEventSchema


class WebhookReceiptSchema(CamelSchema):
    received: bool
    duplicate: bool
