import json

import pytest

from finance_autotests.main_backend import (
    RESULT_MARKER,
    MainBackendFixtureFactory,
)


def test_parse_result_uses_explicit_marker() -> None:
    payload = {
        "order_id": "123",
        "payment_id": "hash",
        "order_item_id": "456",
        "product_id": "789",
        "category_id": "10",
        "shop_id": "59",
        "merchant_id": "merchant",
        "provider_reference": "qid",
        "total_amount": "1000.00",
    }
    stdout = "django log\n" + RESULT_MARKER + json.dumps(payload) + "\n"

    assert MainBackendFixtureFactory._parse_result(stdout) == payload


def test_parse_result_rejects_output_without_marker() -> None:
    with pytest.raises(RuntimeError):
        MainBackendFixtureFactory._parse_result("django log only")


def test_fixture_code_requires_test_shop_and_customer() -> None:
    code = MainBackendFixtureFactory._fixture_code(
        run_id="qa-run",
        shop_id=59,
        client_phone="996700000001",
    )

    assert "user_type=User.TYPE_CUSTOMER" in code
    assert "if not shop.is_test:" in code
