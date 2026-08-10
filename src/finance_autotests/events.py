from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4


@dataclass(frozen=True)
class KafkaMessage:
    topic: str
    key: str
    value: dict


@dataclass(frozen=True)
class OrderPaidMessage:
    message: KafkaMessage
    order_id: str
    payment_id: str
    item_id: str


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _numeric_order_id() -> str:
    return str(100_000_000 + uuid4().int % 900_000_000)


def merchant_created_message(merchant_id: str) -> KafkaMessage:
    return KafkaMessage(
        topic="merchants.merchant.created",
        key=merchant_id,
        value={
            "event_type": "merchant.created",
            "payload": {
                "merchant_id": merchant_id,
                "organization_name": "Local Autotest Merchant",
                "email": f"{merchant_id}@autotest.local",
                "available_installment_months": [3, 6],
            },
            "timestamp": _timestamp(),
        },
    )


def order_paid_message(
    merchant_id: str,
    *,
    payment_source_type: str = "MBANK",
    installment_plan: int = 0,
    amount: str = "1000.00",
) -> OrderPaidMessage:
    run_id = uuid4().hex
    order_id = _numeric_order_id()
    payment_id = f"autotest-payment-{run_id}"
    item_id = f"autotest-item-{run_id}"
    value = {
        "event_type": "order.paid",
        "payload": {
            "id": payment_id,
            "order_id": order_id,
            "client_id": f"autotest-client-{run_id}",
            "client_phone": "996700000001",
            "status": "PAID",
            "installment_plan": installment_plan,
            "payment_sources": [{
                "type": payment_source_type,
                "amount": amount,
                "provider_reference": f"autotest-provider-{run_id}",
            }],
            "order_snapshot": {
                "currency": "KGS",
                "total_amount": amount,
                "delivery": None,
                "certificate": None,
                "items": [{
                    "order_item_id": item_id,
                    "product_id": f"autotest-product-{run_id}",
                    "category_id": f"autotest-category-{run_id}",
                    "shop_id": f"autotest-shop-{run_id}",
                    "merchant_id": merchant_id,
                    "price": amount,
                    "quantity": 1,
                    "item_total": amount,
                    "cashback_percent": 0,
                }],
            },
        },
        "timestamp": _timestamp(),
    }
    return OrderPaidMessage(
        message=KafkaMessage("payments.order.paid", order_id, value),
        order_id=order_id,
        payment_id=payment_id,
        item_id=item_id,
    )


def order_completed_message(order_id: str) -> KafkaMessage:
    timestamp = _timestamp()
    return KafkaMessage(
        topic="orders.order.completed",
        key=order_id,
        value={
            "event_type": "order.completed",
            "payload": {
                "order_id": order_id,
                "status": "COMPLETED",
                "completed_at": timestamp,
            },
            "timestamp": timestamp,
        },
    )
