import pytest

from tests.functional.support import PaymentScenario, run_payment_flow


@pytest.mark.functional
@pytest.mark.smoke
def test_payment_mbank_credit_and_split(market_scenario_factory) -> None:
    run_payment_flow(PaymentScenario(payment="MBANK"), market_scenario_factory)
