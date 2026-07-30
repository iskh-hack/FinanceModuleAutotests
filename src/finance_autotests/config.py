from __future__ import annotations

import os
from dataclasses import dataclass


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Не задана обязательная переменная окружения {name}")
    return value


@dataclass(frozen=True)
class Settings:
    allow_side_effects: bool
    kafka_brokers: str
    kafka_order_paid_topic: str
    kafka_security_protocol: str
    kafka_sasl_mechanism: str
    kafka_username: str
    kafka_password: str
    postgres_dsn: str
    test_merchant_id: str
    test_shop_id: str
    test_product_id: str
    test_category_id: str
    wait_timeout_seconds: float
    wait_interval_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            allow_side_effects=_as_bool(os.getenv("FM_ALLOW_SIDE_EFFECTS")),
            kafka_brokers=_required("FM_KAFKA_BROKERS"),
            kafka_order_paid_topic=os.getenv(
                "FM_KAFKA_ORDER_PAID_TOPIC", "payments.order.paid"
            ).strip(),
            kafka_security_protocol=os.getenv(
                "FM_KAFKA_SECURITY_PROTOCOL", "SASL_SSL"
            ).strip(),
            kafka_sasl_mechanism=os.getenv(
                "FM_KAFKA_SASL_MECHANISM", "PLAIN"
            ).strip(),
            kafka_username=os.getenv("FM_KAFKA_USERNAME", "").strip(),
            kafka_password=os.getenv("FM_KAFKA_PASSWORD", "").strip(),
            postgres_dsn=_required("FM_POSTGRES_DSN"),
            test_merchant_id=_required("FM_TEST_MERCHANT_ID"),
            test_shop_id=_required("FM_TEST_SHOP_ID"),
            test_product_id=_required("FM_TEST_PRODUCT_ID"),
            test_category_id=_required("FM_TEST_CATEGORY_ID"),
            wait_timeout_seconds=float(
                os.getenv("FM_WAIT_TIMEOUT_SECONDS", "60")
            ),
            wait_interval_seconds=float(
                os.getenv("FM_WAIT_INTERVAL_SECONDS", "2")
            ),
        )

