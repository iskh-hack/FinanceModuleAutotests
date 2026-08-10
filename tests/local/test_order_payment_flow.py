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
    (
        "source_type",
        "installment_plan",
        "expected_method",
        "source_account",
        "amount",
        "extra_transaction",
        "extra_transaction_amount",
    ),
    [
        pytest.param("MBANK", 0, "mbank", "@mbank_deposit", "1000.00", None, None, id="mbank"),
        pytest.param("OTP", 0, "mbank_pay", "@mbank_pay_deposit", "1000.00", None, None, id="otp"),
        pytest.param("PAYLER", 0, "payler", "@payler_deposit", "1000.00", None, None, id="payler"),
        pytest.param(
            "MPLUS", 6, "mplus", "@mplus_deposit", "1000.00",
            "MPLUS_COMMISSION", "55.00", id="mplus-6-months",
        ),
        pytest.param(
            "ADAL", 4, "adal", "@adal_deposit", "235.00",
            "ADAL_COMMISSION", "9.40", id="adal-4-months-rounding",
        ),
    ],
)
def test_order_paid_credit_and_split_local(
    source_type: str,
    installment_plan: int,
    expected_method: str,
    source_account: str,
    amount: str,
    extra_transaction: str | None,
    extra_transaction_amount: str | None,
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
        amount=amount,
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
        assert db.amount(credited["amount"]) == Decimal(amount)

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
        transactions = db.order_transactions(paid.payment_id)
        transaction_types = {row["transaction_type"] for row in transactions}
        assert "MERCHANT_TRANSIT" in transaction_types
        assert "MERCHANT_BLOCK" in transaction_types
        transit = next(
            row for row in transactions if row["transaction_type"] == "MERCHANT_TRANSIT"
        )
        assert transit["metadata"]["payment_method"] == expected_method
        assert transit["metadata"]["funding_sources"][0]["source_account"] == source_account
        if extra_transaction:
            assert extra_transaction in transaction_types
            provider_commission = next(
                row for row in transactions
                if row["transaction_type"] == extra_transaction
            )
            assert db.amount(provider_commission["amount"]) == Decimal(
                extra_transaction_amount
            )
