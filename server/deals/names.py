import re
from decimal import Decimal, InvalidOperation

LEADING_DOLLAR_PRICE = re.compile(
    r"^\s*\$\s*(?P<low>\d+(?:\.\d{1,2})?)"
    r"(?:\s*(?:-|–|—|to)\s*\$?\s*(?P<high>\d+(?:\.\d{1,2})?))?"
    r"(?P<separator>\s*[:·]\s*|\s+|$)",
    flags=re.IGNORECASE,
)
LEADING_PERCENT_PRICE = re.compile(
    r"^\s*(?P<percent>\d+(?:\.\d+)?)\s*%\s*(?:off\b)?"
    r"(?P<separator>\s*[:·]\s*|\s+|$)",
    flags=re.IGNORECASE,
)


def _cents(value: str) -> int | None:
    try:
        amount = Decimal(value) * 100
    except InvalidOperation:
        return None
    return int(amount) if amount == amount.to_integral_value() else None


def public_deal_name(
    value: str,
    *,
    price_kind: str,
    price_cents: int | None = None,
    price_low_cents: int | None = None,
    price_high_cents: int | None = None,
    discount_percent: Decimal | float | int | None = None,
) -> str:
    """Remove only a leading price that exactly repeats structured price data."""

    trimmed = value.strip()
    dollar = LEADING_DOLLAR_PRICE.match(trimmed)
    if dollar is not None:
        low = _cents(dollar.group("low"))
        high_text = dollar.group("high")
        high = _cents(high_text) if high_text is not None else None
        repeats_single = (
            price_kind in {"absolute", "single"} and high is None and low == price_cents
        )
        repeats_range = (
            price_kind == "range"
            and high is not None
            and low == price_low_cents
            and high == price_high_cents
        )
        if repeats_single or repeats_range:
            return trimmed[dollar.end() :].strip()

    percent = LEADING_PERCENT_PRICE.match(trimmed)
    if percent is not None and price_kind in {"relative", "percent_off"}:
        try:
            structured = Decimal(str(discount_percent))
            named = Decimal(percent.group("percent"))
        except InvalidOperation, TypeError:
            pass
        else:
            if named == structured:
                return trimmed[percent.end() :].strip()

    return trimmed
