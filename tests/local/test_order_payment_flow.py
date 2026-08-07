from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
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


def _terminal_merchant(db: FinanceDatabase, merchant_id: str):
    job = db.merchant_job(merchant_id)
    return job if job and job["status"] in {"COMPLETED", "FAILED"} else None


@pytest.mark.local_e2e
@pytest.mark.smoke
def test_order_paid_credit_and_split_local() -> None:
    if not _enabled("FM_LOCAL_E2E"):
        pytest.skip("Локальный E2E отключён: задайте FM_LOCAL_E2E=true")

    dsn = os.getenv(
        "FM_LOCAL_POSTGRES_DSN",
        "postgresql://user:user@localhost:5434/fin_module",
    )
    kafka = os.getenv("FM_LOCAL_KAFKA", "localhost:9092")
    timeout = float(os.getenv("FM_LOCAL_WAIT_TIMEOUT_SECONDS", "90"))
    interval = float(os.getenv("FM_LOCAL_WAIT_INTERVAL_SECONDS", "1"))
    db = FinanceDatabase(dsn)

    assert not db.server_is_read_only(), "Локальная БД неожиданно read-only"

    run_id = uuid4().hex
    merchant_id = f"autotest-merchant-{run_id}"
    order_id = f"autotest-order-{run_id}"
    payment_id = f"autotest-payment-{run_id}"
    item_id = f"autotest-item-{run_id}"
    timestamp = datetime.now(UTC).isoformat()

    merchant_event = {
        "event_type": "merchant.created",
        "payload": {
            "merchant_id": merchant_id,
            "organization_name": "Local Autotest Merchant",
            "email": f"{run_id}@autotest.local",
            "available_installment_months": [3, 6],
        },
        "timestamp": timestamp,
    }
    paid_event = {
        "event_type": "order.paid",
        "payload": {
            "id": payment_id,
            "order_id": order_id,
            "client_id": f"autotest-client-{run_id}",
            "client_phone": "996700000001",
            "status": "PAID",
            "payment_sources": [
                {
                    "type": "MBANK",
                    "amount": "1000.00",
                    "provider_reference": f"autotest-provider-{run_id}",
                }
            ],
            "order_snapshot": {
                "currency": "KGS",
                "total_amount": "1000.00",
                "items": [
                    {
                        "order_item_id": item_id,
                        "product_id": f"autotest-product-{run_id}",
                        "category_id": f"autotest-category-{run_id}",
                        "shop_id": f"autotest-shop-{run_id}",
                        "merchant_id": merchant_id,
                        "price": "1000.00",
                        "quantity": 1,
                        "item_total": "1000.00",
                        "cashback_percent": 0,
                    }
                ],
            },
        },
        "timestamp": timestamp,
    }
    completed_event = {
        "event_type": "order.completed",
        "payload": {
            "order_id": order_id,
            "status": "COMPLETED",
            "completed_at": datetime.now(UTC).isoformat(),
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }

    with KafkaPublisher(kafka) as publisher:
        publisher.publish("merchants.merchant.created", merchant_event)
        merchant_job = wait_for(
            lambda: _terminal_merchant(db, merchant_id),
            timeout=timeout,
            interval=interval,
            description=f"COMPLETED merchant_job для {merchant_id}",
        )
        assert merchant_job["status"] == "COMPLETED", merchant_job["last_error"]
        account_types = {row["account_type"] for row in db.merchant_accounts(merchant_id)}
        assert "transit" in account_types
        assert "current" in account_types

        publisher.publish("payments.order.paid", paid_event)
        credited = wait_for(
            lambda: _terminal_job(db, payment_id, {"CREDITED", "FAILED"}),
            timeout=timeout,
            interval=interval,
            description=f"CREDITED payment_job для {payment_id}",
        )
        assert credited["status"] == "CREDITED", credited["last_error"]
        assert credited["credit_txn_id"]
        assert credited["credited_at"] is not None
        assert db.amount(credited["amount"]) == Decimal("1000.00")

        snapshot = db.snapshot(payment_id)
        assert snapshot is not None
        assert snapshot["order_id"] == order_id
        assert db.amount(snapshot["total_amount"]) == Decimal("1000.00")
        items = db.snapshot_items(payment_id)
        assert len(items) == 1
        assert items[0]["order_item_id"] == item_id
        assert items[0]["merchant_id"] == merchant_id

        credit_transactions = db.order_transactions(payment_id)
        assert any(row["transaction_type"] == "MERCHANT_TRANSIT" for row in credit_transactions)

        publisher.publish("orders.order.completed", completed_event)
        split = wait_for(
            lambda: _terminal_job(db, payment_id, {"SPLIT_COMPLETED", "FAILED"}),
            timeout=timeout,
            interval=interval,
            description=f"SPLIT_COMPLETED payment_job для {payment_id}",
        )
        assert split["status"] == "SPLIT_COMPLETED", split["last_error"]
        assert split["last_error"] in {None, ""}

        split_transactions = db.order_transactions(payment_id)
        transaction_types = {row["transaction_type"] for row in split_transactions}
        assert "MERCHANT_BLOCK" in transaction_types
