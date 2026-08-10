from finance_autotests.events import order_completed_message, order_paid_message


def test_regular_payment_contract_uses_zero_installment_plan() -> None:
    paid = order_paid_message("merchant-1")

    assert paid.order_id.isdigit()
    assert paid.message.key == paid.order_id
    assert paid.message.value["payload"]["order_id"] == paid.order_id
    assert paid.message.value["payload"]["installment_plan"] == 0
    assert paid.message.value["payload"]["order_snapshot"]["certificate"] is None
    assert paid.message.value["payload"]["order_snapshot"]["delivery"] is None


def test_mplus_contract_contains_installment_plan() -> None:
    paid = order_paid_message(
        "merchant-1",
        payment_source_type="MPLUS",
        installment_plan=6,
    )

    assert paid.message.value["payload"]["installment_plan"] == 6
    assert paid.message.value["payload"]["payment_sources"][0]["type"] == "MPLUS"


def test_order_completed_uses_order_id_as_kafka_key() -> None:
    completed = order_completed_message("123456789")

    assert completed.key == "123456789"
    assert completed.value["payload"]["order_id"] == "123456789"
