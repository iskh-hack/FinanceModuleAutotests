from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from finance_autotests.database import FinanceDatabase
from finance_autotests.kafka_client import KafkaPublisher
from finance_autotests.polling import wait_for


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _terminal_job(db: FinanceDatabase, payment_id: str, statuses: set[str]):
    job = db.payment_job(payment_id)
    return job if job and job["status"] in statuses else None


def _merchant_ready(db: FinanceDatabase, merchant_id: str):
    job = db.merchant_job(merchant_id)
    return job if job and job["status"] in {"COMPLETED", "FAILED"} else None


def _events(merchant_id: str) -> tuple[str, str, dict, dict]:
    run_id = uuid4().hex
    order_id = str(100_000_000 + uuid4().int % 900_000_000)
    payment_id = f"resilience-payment-{run_id}"
    timestamp = datetime.now(UTC).isoformat()
    paid = {
        "event_type": "order.paid",
        "payload": {
            "id": payment_id,
            "order_id": order_id,
            "client_id": f"resilience-client-{run_id}",
            "client_phone": "996700000001",
            "status": "PAID",
            "installment_plan": 0,
            "payment_sources": [{
                "type": "MBANK",
                "amount": "1000.00",
                "provider_reference": f"resilience-provider-{run_id}",
            }],
            "order_snapshot": {
                "currency": "KGS",
                "total_amount": "1000.00",
                "delivery": None,
                "certificate": None,
                "items": [{
                    "order_item_id": f"resilience-item-{run_id}",
                    "product_id": f"resilience-product-{run_id}",
                    "category_id": f"resilience-category-{run_id}",
                    "shop_id": f"resilience-shop-{run_id}",
                    "merchant_id": merchant_id,
                    "price": "1000.00",
                    "quantity": 1,
                    "item_total": "1000.00",
                    "cashback_percent": 0,
                }],
            },
        },
        "timestamp": timestamp,
    }
    completed = {
        "event_type": "order.completed",
        "payload": {
            "order_id": order_id,
            "status": "COMPLETED",
            "completed_at": timestamp,
        },
        "timestamp": timestamp,
    }
    return order_id, payment_id, paid, completed


@pytest.fixture(scope="module")
def local_flow():
    if not _enabled("FM_LOCAL_E2E"):
        pytest.skip("Локальный E2E отключён: задайте FM_LOCAL_E2E=true")

    db = FinanceDatabase(os.getenv(
        "FM_LOCAL_POSTGRES_DSN",
        "postgresql://user:user@localhost:5434/fin_module",
    ))
    publisher = KafkaPublisher(os.getenv("FM_LOCAL_KAFKA", "localhost:9092"))
    timeout = float(os.getenv("FM_LOCAL_WAIT_TIMEOUT_SECONDS", "90"))
    interval = float(os.getenv("FM_LOCAL_WAIT_INTERVAL_SECONDS", "1"))
    merchant_id = f"resilience-merchant-{uuid4().hex}"
    event = {
        "event_type": "merchant.created",
        "payload": {
            "merchant_id": merchant_id,
            "organization_name": "Resilience Autotest Merchant",
            "email": f"{merchant_id}@autotest.local",
            "available_installment_months": [3, 6],
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }
    publisher.publish("merchants.merchant.created", event, key=merchant_id)
    job = wait_for(
        lambda: _merchant_ready(db, merchant_id),
        timeout=timeout,
        interval=interval,
        description=f"COMPLETED merchant_job для {merchant_id}",
    )
    assert job["status"] == "COMPLETED", job["last_error"]
    yield db, publisher, merchant_id, timeout, interval
    publisher.close()


@pytest.mark.local_e2e
def test_duplicate_order_paid_is_idempotent(local_flow) -> None:
    db, publisher, merchant_id, timeout, interval = local_flow
    _, payment_id, paid, _ = _events(merchant_id)

    publisher.publish("payments.order.paid", paid, key=paid["payload"]["order_id"])
    publisher.publish("payments.order.paid", paid, key=paid["payload"]["order_id"])
    job = wait_for(
        lambda: _terminal_job(db, payment_id, {"CREDITED", "FAILED"}),
        timeout=timeout,
        interval=interval,
        description=f"CREDITED payment_job для {payment_id}",
    )
    assert job["status"] == "CREDITED", job["last_error"]
    time.sleep(3)
    assert db.payment_job_count(payment_id) == 1
    assert db.order_transaction_count(payment_id, "MERCHANT_TRANSIT") == 1


@pytest.mark.local_e2e
def test_duplicate_order_completed_is_idempotent(local_flow) -> None:
    db, publisher, merchant_id, timeout, interval = local_flow
    _, payment_id, paid, completed = _events(merchant_id)

    publisher.publish("payments.order.paid", paid, key=paid["payload"]["order_id"])
    credited = wait_for(
        lambda: _terminal_job(db, payment_id, {"CREDITED", "FAILED"}),
        timeout=timeout,
        interval=interval,
        description=f"CREDITED payment_job для {payment_id}",
    )
    assert credited["status"] == "CREDITED", credited["last_error"]
    publisher.publish("orders.order.completed", completed, key=completed["payload"]["order_id"])
    publisher.publish("orders.order.completed", completed, key=completed["payload"]["order_id"])
    split = wait_for(
        lambda: _terminal_job(db, payment_id, {"SPLIT_COMPLETED", "FAILED"}),
        timeout=timeout,
        interval=interval,
        description=f"SPLIT_COMPLETED payment_job для {payment_id}",
    )
    assert split["status"] == "SPLIT_COMPLETED", split["last_error"]
    time.sleep(3)
    assert db.payment_job_count(payment_id) == 1
    assert db.order_transaction_count(payment_id, "MERCHANT_TRANSIT") == 1
    assert db.order_transaction_count(payment_id, "MERCHANT_BLOCK") == 1


@pytest.mark.local_e2e
def test_order_completed_before_order_paid_is_deferred(local_flow) -> None:
    db, publisher, merchant_id, timeout, interval = local_flow
    order_id, payment_id, paid, completed = _events(merchant_id)

    publisher.publish("orders.order.completed", completed, key=order_id)
    intent = wait_for(
        lambda: db.completion_intent(order_id),
        timeout=timeout,
        interval=interval,
        description=f"completion intent для {order_id}",
    )
    assert intent["processed"] is False

    publisher.publish("payments.order.paid", paid, key=order_id)
    split = wait_for(
        lambda: _terminal_job(db, payment_id, {"SPLIT_COMPLETED", "FAILED"}),
        timeout=timeout,
        interval=interval,
        description=f"SPLIT_COMPLETED payment_job для {payment_id}",
    )
    assert split["status"] == "SPLIT_COMPLETED", split["last_error"]
    processed = db.completion_intent(order_id)
    assert processed is not None
    assert processed["processed"] is True
    assert processed["processed_at"] is not None
    assert db.order_transaction_count(payment_id, "MERCHANT_TRANSIT") == 1
    assert db.order_transaction_count(payment_id, "MERCHANT_BLOCK") == 1
