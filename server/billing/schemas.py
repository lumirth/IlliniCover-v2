from datetime import datetime

from config.schemas import CamelSchema
from pydantic import Field, field_validator


class EntitlementSchema(CamelSchema):
    identifier: str
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
    entitlement_ids: list[str] | None = None
    expiration_at_ms: int | None = None
    event_timestamp_ms: int | None = None
    environment: str | None = Field(default=None, max_length=24)
    transferred_from: list[str] = Field(default_factory=list)
    transferred_to: list[str] = Field(default_factory=list)

    @field_validator("environment")
    @classmethod
    def known_environment(cls, value):
        if value is None:
            return None
        normalized = value.strip().upper()
        if normalized not in {"SANDBOX", "PRODUCTION"}:
            raise ValueError("environment must be SANDBOX or PRODUCTION")
        return normalized


class RevenueCatEnvelopeSchema(CamelSchema):
    api_version: str | None = None
    event: RevenueCatEventSchema


class WebhookReceiptSchema(CamelSchema):
    received: bool
    duplicate: bool
