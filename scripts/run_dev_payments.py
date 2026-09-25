from __future__ import annotations

import argparse
import json
import os

from finance_autotests.core_backend import (
    SCENARIO_METHODS,
    CoreBackendScenarioConfig,
    CoreBackendScenarioFactory,
)
from finance_autotests.flow import run_created_order_happy_path

_TRUE_VALUES = {"1", "true", "yes", "on"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create real Core Backend orders and verify Finance Module CREDIT -> SPLIT",
    )
    parser.add_argument(
        "--payment",
        choices=[*SCENARIO_METHODS, "ALL"],
        default="MBANK",
    )
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()
    _require_safe_environment(parser)

    scenario_config = CoreBackendScenarioConfig(
        kubectl_path=os.environ["FM_KUBECTL_PATH"],
        kubeconfig=os.environ["FM_KUBECONFIG"],
        namespace=os.getenv("FM_KUBE_NAMESPACE", "market"),
        resource=os.environ["FM_MAIN_BACKEND_RESOURCE"],
        container=os.getenv(
            "FM_MAIN_BACKEND_CONTAINER",
            "service-market-core-backend-api",
        ),
        timeout_seconds=int(os.getenv("FM_SCENARIO_TIMEOUT_SECONDS", "180")),
    )
    factory = CoreBackendScenarioFactory(scenario_config)
    selected = list(SCENARIO_METHODS) if args.payment == "ALL" else [args.payment]
    results = [
        run_created_order_happy_path(
            scenario=factory.create(
                payment=payment,
                shop_id=os.getenv("FM_TEST_SHOP_ID", "273"),
                run_id=(f"{args.run_id}-{payment.lower()}" if args.run_id else None),
            ),
            scenario_factory=factory,
            postgres_dsn=os.environ["FM_POSTGRES_DSN"],
            timeout=args.timeout,
            interval=float(os.getenv("FM_WAIT_INTERVAL_SECONDS", "2")),
            log=print,
        ).as_dict()
        for payment in selected
    ]
    print(json.dumps(results, ensure_ascii=False, indent=2))


def _require_safe_environment(parser: argparse.ArgumentParser) -> None:
    for flag in ("FM_ALLOW_SIDE_EFFECTS", "FM_CONFIRM_DOWNSTREAM_ISOLATED"):
        if os.getenv(flag, "").lower() not in _TRUE_VALUES:
            parser.error(f"Set {flag}=true")
    required = (
        "FM_POSTGRES_DSN",
        "FM_KUBECTL_PATH",
        "FM_KUBECONFIG",
        "FM_MAIN_BACKEND_RESOURCE",
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        parser.error("Missing environment variables: " + ", ".join(missing))


if __name__ == "__main__":
    main()
