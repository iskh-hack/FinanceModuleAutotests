from decimal import Decimal

import pytest

from finance_autotests.events import build_order_paid


def test_build_order_paid_produces_unique_consistent_contract() -> None:
    first = build_order_paid(
        merchant_id="merchant",
        shop_id="shop",
        product_id="product",
        category_id="category",
        item_total=Decimal("1000.00"),
    )
    second = build_order_paid(
        merchant_id="merchant",
        shop_id="shop",
        product_id="product",
        category_id="category",
        item_total=Decimal("1000.00"),
    )

    assert first.order_id != second.order_id
    assert first.payment_id != second.payment_id
    assert first.event["payload"]["id"] == first.payment_id
    assert first.event["payload"]["order_id"] == first.order_id
    assert first.event["payload"]["payment_sources"][0]["amount"] == 1000
    assert first.event["payload"]["order_snapshot"]["total_amount"] == 1000
    assert (
        first.event["payload"]["order_snapshot"]["items"][0]["item_total"]
        == 1000
    )


@pytest.mark.parametrize(
    ("amount", "quantity"),
    [
        (Decimal("0"), 1),
        (Decimal("-1"), 1),
        (Decimal("100"), 0),
    ],
)
def test_build_order_paid_rejects_invalid_money_or_quantity(
    amount: Decimal,
    quantity: int,
) -> None:
    with pytest.raises(ValueError):
        build_order_paid(
            merchant_id="merchant",
            shop_id="shop",
            product_id="product",
            category_id="category",
            item_total=amount,
            quantity=quantity,
        )

