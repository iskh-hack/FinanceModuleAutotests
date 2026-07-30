from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4


def _json_amount(value: Decimal) -> int | float:
    """Возвращает JSON number; проверки точности выполняются через Decimal."""
    if value == value.to_integral():
        return int(value)
    return float(value)


@dataclass(frozen=True)
class OrderPaidData:
    event: dict[str, Any]
    order_id: str
    payment_id: str
    order_item_id: str
    expected_amount: Decimal


def build_order_paid(
    *,
    merchant_id: str,
    shop_id: str,
    product_id: str,
    category_id: str,
    item_total: Decimal = Decimal("1000.00"),
    quantity: int = 1,
    payment_source_type: str = "MBANK",
) -> OrderPaidData:
    if item_total <= 0:
        raise ValueError("item_total должен быть больше нуля")
    if quantity <= 0:
        raise ValueError("quantity должен быть больше нуля")

    suffix = uuid4().hex
    order_id = f"autotest-order-{suffix}"
    payment_id = f"autotest-payment-{suffix}"
    order_item_id = f"autotest-item-{suffix}"
    provider_reference = f"autotest-provider-{suffix}"

    event = {
        "event_type": "order.paid",
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "payload": {
            "id": payment_id,
            "order_id": order_id,
            "client_id": f"autotest-client-{suffix}",
            "client_phone": "996700000001",
            "status": "PAID",
            "payment_sources": [
                {
                    "type": payment_source_type,
                    "amount": _json_amount(item_total),
                    "provider_reference": provider_reference,
                }
            ],
            "order_snapshot": {
                "currency": "KGS",
                "total_amount": _json_amount(item_total),
                "items": [
                    {
                        "order_item_id": order_item_id,
                        "product_id": product_id,
                        "category_id": category_id,
                        "shop_id": shop_id,
                        "merchant_id": merchant_id,
                        "price": _json_amount(item_total),
                        "quantity": quantity,
                        "item_total": _json_amount(item_total),
                    }
                ],
            },
        },
    }

    return OrderPaidData(
        event=event,
        order_id=order_id,
        payment_id=payment_id,
        order_item_id=order_item_id,
        expected_amount=item_total,
    )

