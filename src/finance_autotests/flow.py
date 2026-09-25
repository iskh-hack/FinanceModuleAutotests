from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

import psycopg

from .core_backend import CoreBackendScenarioFactory, CreatedOrderScenario
from .database import FinanceDatabase
from .polling import wait_for


@dataclass(frozen=True)
class HappyPathResult:
    payment: str
    order_id: str
    payment_id: str
    merchant_id: str
    amount: str
    credit_status: str
    core_status: str
    split_status: str

    def as_dict(self) -> dict:
        return asdict(self)


def run_created_order_happy_path(
    *,
    scenario: CreatedOrderScenario,
    scenario_factory: CoreBackendScenarioFactory,
    postgres_dsn: str,
    timeout: float = 240,
    interval: float = 2,
    log: Callable[[str], None] | None = None,
) -> HappyPathResult:
    """Run a consistent Core Backend -> Debezium -> Finance Module flow."""
    report = log or (lambda _message: None)
    db = FinanceDatabase(postgres_dsn)
    report(
        f"[{scenario.payment}] real order_id={scenario.order_id} "
        f"order_code={scenario.order_code} payment_id={scenario.payment_id}"
    )

    credited = wait_for(
        lambda: _job_in(db, scenario.payment_id, {"CREDITED", "FAILED"}),
        timeout=timeout,
        interval=interval,
        description=f"CREDITED payment_job for {scenario.payment_id}",
        retry_exceptions=(psycopg.OperationalError,),
    )
    _assert_created_order_credited(db, scenario, credited)
    report(f"[{scenario.payment}] CREDITED")

    scenario_factory.complete(scenario)
    report(f"[{scenario.payment}] Core Backend status=DELIVERED")

    split = wait_for(
        lambda: _job_in(db, scenario.payment_id, {"SPLIT_COMPLETED", "FAILED"}),
        timeout=timeout,
        interval=interval,
        description=f"SPLIT_COMPLETED payment_job for {scenario.payment_id}",
        retry_exceptions=(psycopg.OperationalError,),
    )
    _assert_created_order_split(db, scenario, split)
    report(f"[{scenario.payment}] SPLIT_COMPLETED")

    return HappyPathResult(
        payment=scenario.payment,
        order_id=scenario.order_id,
        payment_id=scenario.payment_id,
        merchant_id=scenario.merchant_id,
        amount=format(scenario.total_sum, "f"),
        credit_status="CREDITED",
        core_status="DELIVERED",
        split_status="SPLIT_COMPLETED",
    )


def _assert_created_order_credited(
    db: FinanceDatabase,
    scenario: CreatedOrderScenario,
    job: dict,
) -> None:
    if job["status"] != "CREDITED":
        raise AssertionError(job["last_error"] or f"CREDIT failed: {job}")
    assert job["order_id"] == scenario.order_id
    assert db.payment_job_count(scenario.payment_id) == 1, "Duplicate payment job"
    assert job["currency"] == "KGS"
    assert job["payment_method"] == scenario.finance_payment_method
    assert job["installment_months"] == scenario.installment_plan
    assert db.amount(job["amount"]) == scenario.total_sum

    snapshot = db.snapshot(scenario.payment_id)
    assert snapshot is not None
    assert snapshot["order_id"] == scenario.order_id
    assert db.amount(snapshot["total_amount"]) == scenario.total_sum
    assert snapshot["currency"] == "KGS"

    items = db.snapshot_items(scenario.payment_id)
    assert items
    assert all(item["merchant_id"] == scenario.merchant_id for item in items)
    assert all(str(item["shop_id"]) == scenario.shop_id for item in items)
    assert all(item["order_item_id"] for item in items)
    assert all(item["product_id"] for item in items)
    assert all(item["category_id"] for item in items)


def _assert_created_order_split(
    db: FinanceDatabase,
    scenario: CreatedOrderScenario,
    job: dict,
) -> None:
    if job["status"] != "SPLIT_COMPLETED":
        raise AssertionError(job["last_error"] or f"SPLIT failed: {job}")
    transactions = db.order_transactions(scenario.payment_id)
    transaction_types = {row["transaction_type"] for row in transactions}
    assert "MERCHANT_TRANSIT" in transaction_types
    assert "MERCHANT_BLOCK" in transaction_types
    assert all(row["blnk_transaction_id"] for row in transactions)
    if scenario.payment == "MBANK":
        items = db.snapshot_items(scenario.payment_id)
        assert len(items) == 1, "MBANK smoke expects one item without delivery"
        assert db.amount(items[0]["item_total"]) == scenario.total_sum
        expected = {"MERCHANT_TRANSIT": scenario.total_sum}
        for kind, field in (("COMMISSION", "marketplace_commission_amount"),
                            ("MBONUS", "mbonus_amount"), ("MERCHANT_BLOCK", "merchant_amount")):
            amount = db.amount(items[0][field])
            assert amount >= 0, f"Negative {field}"
            if amount > 0:
                expected[kind] = amount
        assert sorted(row["transaction_type"] for row in transactions) == sorted(expected), "Missing/extra/duplicate entries"
        assert sum(value for kind, value in expected.items() if kind != "MERCHANT_TRANSIT") == scenario.total_sum
        for row in transactions:
            assert db.amount(row["amount"]) == expected[row["transaction_type"]], f"Wrong amount: {row['transaction_type']}"
            assert row["merchant_id"] == scenario.merchant_id, "Wrong merchant"
        assert len({row["blnk_transaction_id"] for row in transactions}) == len(transactions), "Duplicate ledger ID"


def _job_in(
    db: FinanceDatabase,
    payment_id: str,
    statuses: set[str],
) -> dict | None:
    job = db.payment_job(payment_id)
    return job if job and job["status"] in statuses else None
