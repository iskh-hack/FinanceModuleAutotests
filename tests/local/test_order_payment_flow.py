from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import pytest

from finance_autotests.database import FinanceDatabase
from finance_autotests.events import (
    merchant_created_message,
    order_completed_message,
    order_paid_message,
)
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
@pytest.mark.parametrize(
    ("source_type", "installment_plan", "expected_method", "extra_transaction"),
    [
        pytest.param("MBANK", 0, "mbank", None, id="mbank"),
        pytest.param("MPLUS", 6, "mplus", "MPLUS_COMMISSION", id="mplus-6-months"),
    ],
)
def test_order_paid_credit_and_split_local(
    source_type: str,
    installment_plan: int,
    expected_method: str,
    extra_transaction: str | None,
) -> None:
    if not _enabled("FM_LOCAL_E2E"):
        pytest.skip("Локальный E2E отключён: задайте FM_LOCAL_E2E=true")

    db = FinanceDatabase(os.getenv(
        "FM_LOCAL_POSTGRES_DSN",
        "postgresql://user:user@localhost:5434/fin_module",
    ))
    kafka = os.getenv("FM_LOCAL_KAFKA", "localhost:9092")
    timeout = float(os.getenv("FM_LOCAL_WAIT_TIMEOUT_SECONDS", "90"))
    interval = float(os.getenv("FM_LOCAL_WAIT_INTERVAL_SECONDS", "1"))
    merchant_id = f"autotest-merchant-{uuid4().hex}"
    paid = order_paid_message(
        merchant_id,
        payment_source_type=source_type,
        installment_plan=installment_plan,
    )

    with KafkaPublisher(kafka) as publisher:
        publisher.publish_message(merchant_created_message(merchant_id))
        merchant_job = wait_for(
            lambda: _terminal_merchant(db, merchant_id),
            timeout=timeout,
            interval=interval,
            description=f"COMPLETED merchant_job для {merchant_id}",
        )
        assert merchant_job["status"] == "COMPLETED", merchant_job["last_error"]

        publisher.publish_message(paid.message)
        credited = wait_for(
            lambda: _terminal_job(db, paid.payment_id, {"CREDITED", "FAILED"}),
            timeout=timeout,
            interval=interval,
            description=f"CREDITED payment_job для {paid.payment_id}",
        )
        assert credited["status"] == "CREDITED", credited["last_error"]
        assert credited["order_id"] == paid.order_id
        assert credited["payment_method"] == expected_method
        assert credited["installment_months"] == installment_plan
        assert db.amount(credited["amount"]) == Decimal("1000.00")

        snapshot = db.snapshot(paid.payment_id)
        assert snapshot is not None
        assert snapshot["order_id"] == paid.order_id
        items = db.snapshot_items(paid.payment_id)
        assert len(items) == 1
        assert items[0]["order_item_id"] == paid.item_id
        assert items[0]["merchant_id"] == merchant_id

        publisher.publish_message(order_completed_message(paid.order_id))
        split = wait_for(
            lambda: _terminal_job(db, paid.payment_id, {"SPLIT_COMPLETED", "FAILED"}),
            timeout=timeout,
            interval=interval,
            description=f"SPLIT_COMPLETED payment_job для {paid.payment_id}",
        )
        assert split["status"] == "SPLIT_COMPLETED", split["last_error"]
        transaction_types = {
            row["transaction_type"] for row in db.order_transactions(paid.payment_id)
        }
        assert "MERCHANT_TRANSIT" in transaction_types
        assert "MERCHANT_BLOCK" in transaction_types
        if extra_transaction:
            assert extra_transaction in transaction_types
