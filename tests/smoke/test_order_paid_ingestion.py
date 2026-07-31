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
