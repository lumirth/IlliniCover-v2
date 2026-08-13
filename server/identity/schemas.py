import uuid
from datetime import datetime

from config.schemas import CamelSchema
from pydantic import Field, field_validator

INSTALLATION_TOKEN_PATTERN = r"^ic_install_[A-Za-z0-9_-]{43,189}$"


class ClientRequestSchema(CamelSchema):
    request_id: uuid.UUID

    @field_validator("request_id")
    @classmethod
    def request_id_must_be_random_uuid4(cls, value: uuid.UUID) -> uuid.UUID:
        if value.version != 4:
            raise ValueError("requestId must be a random UUIDv4")
        return value


class InstallationRequestSchema(ClientRequestSchema):
    installation_token: str = Field(
        min_length=54,
        max_length=200,
        pattern=INSTALLATION_TOKEN_PATTERN,
    )


class RotateInstallationSchema(ClientRequestSchema):
    replacement_installation_token: str = Field(
        min_length=54,
        max_length=200,
        pattern=INSTALLATION_TOKEN_PATTERN,
    )


class InstallationIssuedSchema(CamelSchema):
    request_id: uuid.UUID
    actor_id: uuid.UUID
    token: str


class CurrentInstallationSchema(CamelSchema):
    actor_id: uuid.UUID


class LinkInstallationSchema(ClientRequestSchema):
    installation_token: str = Field(
        min_length=54,
        max_length=200,
        pattern=INSTALLATION_TOKEN_PATTERN,
    )


class LinkedInstallationSchema(CamelSchema):
    request_id: uuid.UUID
    actor_id: uuid.UUID
    account_id: uuid.UUID


class AccountSchema(CamelSchema):
    id: uuid.UUID
    email: str
    display_name: str


class DeletedSchema(CamelSchema):
    request_id: uuid.UUID
    deleted: bool
    completed_at: datetime


class AccountDeletionRequestSchema(ClientRequestSchema):
    pass
