import pytest

from deals.names import public_deal_name


@pytest.mark.parametrize(
    ("source", "structured", "expected"),
    [
        ("$5 Wells", {"price_kind": "single", "price_cents": 500}, "Wells"),
        (
            "$3-$5 Wings",
            {"price_kind": "range", "price_low_cents": 300, "price_high_cents": 500},
            "Wings",
        ),
        (
            "$3 to $5: Wells Before Ten",
            {"price_kind": "range", "price_low_cents": 300, "price_high_cents": 500},
            "Wells Before Ten",
        ),
        ("$4.50 · Drafts", {"price_kind": "single", "price_cents": 450}, "Drafts"),
        (
            "50% off Appetizers",
            {"price_kind": "percent_off", "discount_percent": 50},
            "Appetizers",
        ),
        ("$5 Footlongs", {"price_kind": "single", "price_cents": 600}, "$5 Footlongs"),
        ("50 Cent Wings", {"price_kind": "single", "price_cents": 50}, "50 Cent Wings"),
        ("Dollar Beer", {"price_kind": "single", "price_cents": 100}, "Dollar Beer"),
        (
            "Wells $3 Before Ten",
            {"price_kind": "single", "price_cents": 300},
            "Wells $3 Before Ten",
        ),
    ],
)
def test_public_deal_name_removes_only_the_matching_leading_structured_price(
    source, structured, expected
):
    assert public_deal_name(source, **structured) == expected
