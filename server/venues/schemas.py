import uuid

from config.schemas import CamelSchema


class VenueSummarySchema(CamelSchema):
    id: uuid.UUID
    slug: str
    name: str
    address: str
    opened_year: int | None
