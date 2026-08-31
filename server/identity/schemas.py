import uuid

from config.schemas import CamelSchema
from pydantic import Field

TOKEN = r"^ic_install_[A-Za-z0-9_-]{43,189}$"


class InstallationRequestSchema(CamelSchema):
    installation_token: str = Field(min_length=54, max_length=200, pattern=TOKEN)


class RotateInstallationSchema(CamelSchema):
    replacement_installation_token: str = Field(min_length=54, max_length=200, pattern=TOKEN)


class InstallationIssuedSchema(CamelSchema):
    actor_id: uuid.UUID


class LinkInstallationSchema(CamelSchema):
    installation_token: str = Field(min_length=54, max_length=200, pattern=TOKEN)


class LinkedInstallationSchema(CamelSchema):
    actor_id: uuid.UUID
    account_id: uuid.UUID


class AccountSchema(CamelSchema):
    id: uuid.UUID
    email: str
    display_name: str
