import re

from ninja import Schema
from pydantic import ConfigDict


def to_camel(value: str) -> str:
    return re.sub(r"_([a-z])", lambda match: match.group(1).upper(), value)


class CamelSchema(Schema):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ErrorSchema(CamelSchema):
    code: str
    message: str
    request_id: str
