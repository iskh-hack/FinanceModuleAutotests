from __future__ import annotations

from decimal import Decimal

import pytest

from finance_autotests.polling import wait_for


@pytest.mark.external
@pytest.mark.smoke
def test_real_mbank_payment_reaches_finance_module(
    settings,
    main_backend,
    finance_db,
) -> None:
    fixture = main_backend.create_mbank_order(
        shop_id=settings.test_shop_id,
        client_phone=settings.test_client_phone,
    )

    job = wait_for(
        lambda: finance_db.payment_job(fixture.payment_id),
        timeout=settings.wait_timeout_seconds,
        interval=settings.wait_interval_seconds,
        description=f"payment_job для {fixture.payment_id}",
    )
    snapshot = wait_for(
        lambda: finance_db.snapshot(fixture.payment_id),
        timeout=settings.wait_timeout_seconds,
        interval=settings.wait_interval_seconds,
        description=f"snapshot для {fixture.payment_id}",
    )
    items = wait_for(
        lambda: finance_db.snapshot_items(fixture.payment_id) or None,
        timeout=settings.wait_timeout_seconds,
        interval=settings.wait_interval_seconds,
        description=f"snapshot items для {fixture.payment_id}",
    )

    assert job["order_id"] == fixture.order_id
    assert job["payment_id"] == fixture.payment_id
    assert finance_db.amount(job["amount"]) == Decimal(fixture.total_amount)

    assert snapshot["order_id"] == fixture.order_id
    assert finance_db.amount(snapshot["total_amount"]) == Decimal(
        fixture.total_amount
    )

    assert len(items) == 1
    assert items[0]["order_item_id"] == fixture.order_item_id
    assert items[0]["merchant_id"] == fixture.merchant_id
    assert items[0]["product_id"] == fixture.product_id
    assert items[0]["category_id"] == fixture.category_id

    credited_job = wait_for(
        lambda: _terminal_payment_job(
            finance_db, fixture.payment_id, {"CREDITED", "FAILED"}
        ),
        timeout=settings.wait_timeout_seconds,
        interval=settings.wait_interval_seconds,
        description=f"CREDIT для {fixture.payment_id}",
    )
    assert credited_job["status"] == "CREDITED", credited_job["last_error"]

    credit_monitoring = wait_for(
        lambda: _completed_monitoring(
            finance_db, fixture.payment_id, "CREDIT"
        ),
        timeout=settings.wait_timeout_seconds,
        interval=settings.wait_interval_seconds,
        description=f"CREDIT monitoring для {fixture.payment_id}",
    )
    assert all(row["blnk_status"] == "APPLIED" for row in credit_monitoring)

    main_backend.complete_order(fixture.order_id)

    split_job = wait_for(
        lambda: _terminal_payment_job(
            finance_db,
            fixture.payment_id,
            {"SPLIT_COMPLETED", "FAILED"},
        ),
        timeout=settings.wait_timeout_seconds,
        interval=settings.wait_interval_seconds,
        description=f"SPLIT для {fixture.payment_id}",
    )
    assert split_job["status"] == "SPLIT_COMPLETED", split_job["last_error"]

    split_monitoring = wait_for(
        lambda: _completed_monitoring(
            finance_db, fixture.payment_id, "SPLIT"
        ),
        timeout=settings.wait_timeout_seconds,
        interval=settings.wait_interval_seconds,
        description=f"SPLIT monitoring для {fixture.payment_id}",
    )
    assert all(row["blnk_status"] == "APPLIED" for row in split_monitoring)


def _terminal_payment_job(finance_db, payment_id: str, statuses: set[str]):
    job = finance_db.payment_job(payment_id)
    return job if job and job["status"] in statuses else None


def _completed_monitoring(finance_db, payment_id: str, operation_type: str):
    rows = finance_db.monitoring_jobs(payment_id, operation_type)
    if not rows:
        return None
    terminal = {"COMPLETED", "FAILED"}
    return rows if all(row["status"] in terminal for row in rows) else None
