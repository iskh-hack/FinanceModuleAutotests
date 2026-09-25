import pytest

from tests.functional.support import PaymentScenario, run_payment_flow


@pytest.mark.functional
def test_payment_mplus_credit_and_split(market_scenario_factory) -> None:
    run_payment_flow(PaymentScenario(payment="MPLUS"), market_scenario_factory)
