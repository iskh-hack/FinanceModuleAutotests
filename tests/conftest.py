from __future__ import annotations

import os

import pytest

from finance_autotests.core_backend import (
    CoreBackendScenarioConfig,
    CoreBackendScenarioFactory,
)


_TRUE_VALUES = {"1", "true", "yes", "on"}


def _require_side_effect_environment() -> None:
    for flag in ("FM_ALLOW_SIDE_EFFECTS", "FM_CONFIRM_DOWNSTREAM_ISOLATED"):
        if os.getenv(flag, "").lower() not in _TRUE_VALUES:
            pytest.skip(f"Functional tests are disabled: set {flag}=true")
    # FM_KUBECTL_PATH/FM_KUBECONFIG/FM_MAIN_BACKEND_RESOURCE are intentionally not required
    # here: MBANK no longer needs kubectl (real Market HTTP flow instead), only the other
    # payment methods still do, and CoreBackendScenarioFactory raises its own clear error
    # when it actually needs one of them and it's missing.
    required = (
        "FM_POSTGRES_DSN",
        "FM_TEST_MERCHANT_ID",
        "FM_TEST_CLIENT_PHONE",
        "FM_TEST_PRODUCT_ID",
        "FM_MARKET_DEV_LOGIN_TOKEN",
        "FM_MBANK_WEBHOOK_TOKEN",
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise pytest.UsageError("Missing environment variables: " + ", ".join(missing))


@pytest.fixture(autouse=True)
def functional_environment(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("functional") is None:
        return

    _require_side_effect_environment()


@pytest.fixture(scope="session")
def market_scenario_factory() -> CoreBackendScenarioFactory:
    _require_side_effect_environment()
    config = CoreBackendScenarioConfig(
        kubectl_path=os.getenv("FM_KUBECTL_PATH", ""),
        kubeconfig=os.getenv("FM_KUBECONFIG", ""),
        namespace=os.getenv("FM_KUBE_NAMESPACE", "market"),
        resource=os.getenv("FM_MAIN_BACKEND_RESOURCE", ""),
        container=os.getenv(
            "FM_MAIN_BACKEND_CONTAINER",
            "service-market-core-backend-api",
        ),
        timeout_seconds=int(os.getenv("FM_SCENARIO_TIMEOUT_SECONDS", "180")),
    )
    return CoreBackendScenarioFactory(config)
