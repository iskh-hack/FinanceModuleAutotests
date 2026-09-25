from __future__ import annotations

import os
from dataclasses import dataclass

from finance_autotests.core_backend import CoreBackendScenarioFactory
from finance_autotests.flow import run_created_order_happy_path
from finance_autotests.market_checkout import MarketCheckoutConfig, MarketCheckoutFactory


@dataclass(frozen=True)
class PaymentScenario:
    payment: str


def run_payment_flow(
    scenario: PaymentScenario,
    factory: CoreBackendScenarioFactory,
) -> None:
    if scenario.payment == "MBANK":
        # Real Market checkout + dispatcher API flow end to end; no kubectl needed.
        completion_factory = _market_checkout_factory()
        created = completion_factory.create(payment=scenario.payment)
    else:
        run_id_prefix = os.getenv("FM_TEST_RUN_ID")
        run_id = f"{run_id_prefix}-{scenario.payment.lower()}" if run_id_prefix else None
        created = factory.create(
            payment=scenario.payment,
            shop_id=os.getenv("FM_TEST_SHOP_ID", "273"),
            run_id=run_id,
        )
        completion_factory = factory
    result = run_created_order_happy_path(
        scenario=created,
        scenario_factory=completion_factory,
        postgres_dsn=os.environ["FM_POSTGRES_DSN"],
        timeout=float(os.getenv("FM_WAIT_TIMEOUT_SECONDS", "240")),
        interval=float(os.getenv("FM_WAIT_INTERVAL_SECONDS", "2")),
        log=print,
    )
    assert result.credit_status == "CREDITED"
    assert result.split_status == "SPLIT_COMPLETED"


def _market_checkout_factory() -> MarketCheckoutFactory:
    config = MarketCheckoutConfig(
        base_url=os.getenv("FM_MARKET_BASE_URL", "https://dev.m-market.kg"),
        client_phone=os.environ["FM_TEST_CLIENT_PHONE"],
        dev_login_token=os.environ["FM_MARKET_DEV_LOGIN_TOKEN"],
        webhook_token=os.environ["FM_MBANK_WEBHOOK_TOKEN"],
        product_id=os.environ["FM_TEST_PRODUCT_ID"],
        merchant_id=os.environ["FM_TEST_MERCHANT_ID"],
        shop_id=os.getenv("FM_TEST_SHOP_ID", "273"),
    )
    return MarketCheckoutFactory(config)
