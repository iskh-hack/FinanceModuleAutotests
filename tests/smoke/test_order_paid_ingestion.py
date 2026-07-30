from __future__ import annotations

from decimal import Decimal

import pytest

from finance_autotests.events import build_order_paid
from finance_autotests.polling import wait_for


@pytest.mark.external
@pytest.mark.smoke
def test_order_paid_creates_job_and_snapshot(
    settings,
    kafka,
    finance_db,
) -> None:
    data = build_order_paid(
        merchant_id=settings.test_merchant_id,
        shop_id=settings.test_shop_id,
        product_id=settings.test_product_id,
        category_id=settings.test_category_id,
        item_total=Decimal("1000.00"),
    )

    kafka.publish_json(
        topic=settings.kafka_order_paid_topic,
        key=data.order_id,
        payload=data.event,
    )

    job = wait_for(
        lambda: finance_db.payment_job(data.payment_id),
        timeout=settings.wait_timeout_seconds,
        interval=settings.wait_interval_seconds,
        description=f"payment_job для {data.payment_id}",
    )
    snapshot = wait_for(
        lambda: finance_db.snapshot(data.payment_id),
        timeout=settings.wait_timeout_seconds,
        interval=settings.wait_interval_seconds,
        description=f"snapshot для {data.payment_id}",
    )
    items = wait_for(
        lambda: finance_db.snapshot_items(data.payment_id) or None,
        timeout=settings.wait_timeout_seconds,
        interval=settings.wait_interval_seconds,
        description=f"snapshot items для {data.payment_id}",
    )

    assert job["order_id"] == data.order_id
    assert job["payment_id"] == data.payment_id
    assert finance_db.amount(job["amount"]) == data.expected_amount

    assert snapshot["order_id"] == data.order_id
    assert finance_db.amount(snapshot["total_amount"]) == data.expected_amount

    assert len(items) == 1
    assert items[0]["order_item_id"] == data.order_item_id
    assert items[0]["merchant_id"] == settings.test_merchant_id
    assert finance_db.amount(items[0]["item_total"]) == data.expected_amount

