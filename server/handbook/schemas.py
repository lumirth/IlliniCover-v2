import uuid
from datetime import datetime

from config.schemas import CamelSchema


class HandbookPageSummarySchema(CamelSchema):
    id: uuid.UUID
    slug: str
    title: str
    summary: str
    updated_at: datetime


class HandbookPageSchema(HandbookPageSummarySchema):
    body_markdown: str
    published_at: datetime | None


class HandbookListSchema(CamelSchema):
    pages: list[HandbookPageSummarySchema]
