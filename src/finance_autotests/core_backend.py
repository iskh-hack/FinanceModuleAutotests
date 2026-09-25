from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4
from .database import FinanceDatabase


SCENARIO_METHODS = {
    "MBANK": "_create_mbank_native_flow",
    "MBANK_PAY": "_create_mbank_pay_flow",
    "PAYLER": "_create_payler_flow",
    "MPLUS": "_create_mplus_flow",
    "ADAL": "_create_adal_flow",
}

PAYMENT_METHODS = {
    "MBANK": "mbank",
    "MBANK_PAY": "mbank_pay",
    "PAYLER": "payler",
    "MPLUS": "mplus",
    "ADAL": "adal",
}

FINANCE_PAYMENT_METHODS = {
    "MBANK": "mbank",
    "MBANK_PAY": "mbank",
    "PAYLER": "payler",
    "MPLUS": "mplus",
    "ADAL": "adal",
}

INSTALLMENT_PLANS = {
    "MBANK": 0,
    "MBANK_PAY": 0,
    "PAYLER": 0,
    "MPLUS": 6,
    "ADAL": 4,
}

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass(frozen=True)
class CoreBackendScenarioConfig:
    kubectl_path: str
    kubeconfig: str
    namespace: str
    resource: str
    container: str = "service-market-core-backend-api"
    timeout_seconds: int = 180


@dataclass(frozen=True)
class CreatedOrderScenario:
    payment: str
    run_id: str
    order_id: str
    order_code: str
    provider_reference: str
    merchant_id: str
    shop_id: str
    total_sum: Decimal
    finance_payment_method: str
    installment_plan: int

    @property
    def payment_id(self) -> str:
        payment_method = PAYMENT_METHODS[self.payment]
        value = f"{payment_method}_{self.order_id}_{self.provider_reference}"
        return hashlib.sha256(value.encode()).hexdigest()


class CoreBackendScenarioFactory:
    """Create one real test order with the deployed developer flow builder."""

    def __init__(self, config: CoreBackendScenarioConfig) -> None:
        self._config = config

    def create(
        self,
        *,
        payment: str,
        shop_id: str,
        run_id: str | None = None,
    ) -> CreatedOrderScenario:
        payment_key = payment.strip().upper()
        if payment_key not in SCENARIO_METHODS:
            supported = ", ".join(SCENARIO_METHODS)
            raise ValueError(f"Unsupported payment {payment!r}; expected: {supported}")
        if not str(shop_id).isdigit():
            raise ValueError("shop_id must be numeric")
        marker = run_id or self._new_run_id(payment_key)
        if not _SAFE_RUN_ID.fullmatch(marker):
            raise ValueError("run_id may contain only letters, digits, dot, underscore and dash")

        if not FinanceDatabase(os.environ["FM_POSTGRES_DSN"]).merchant_accounts(os.environ["FM_TEST_MERCHANT_ID"]):
            raise RuntimeError("Test merchant has no accounts in the selected FM database")
        print(f"Creating {payment_key}: run_id={marker}; setup is not automatically retried", flush=True)
        stdout = self._execute_script(
            _scenario_script(payment_key, str(shop_id), marker)
        )
        return _build_scenario(_extract_summary(stdout))

    def complete(self, scenario: CreatedOrderScenario) -> None:
        stdout = self._execute_script(_completion_script(scenario))
        if "QA_ORDER_COMPLETED=1" not in stdout.splitlines():
            raise RuntimeError("Core Backend did not confirm order completion")

    def _execute_script(self, script: str) -> str:
        encoded_script = base64.b64encode(script.encode()).decode("ascii")
        python_code = (
            "import base64;"
            f"exec(base64.b64decode('{encoded_script}').decode())"
        )
        command = [
            self._config.kubectl_path,
            "--kubeconfig",
            self._config.kubeconfig,
            "--insecure-skip-tls-verify=true",
            "-n",
            self._config.namespace,
            "exec",
            self._config.resource,
            "-c",
            self._config.container,
            "--",
            "python",
            "manage.py",
            "shell",
            "-c",
            python_code,
        ]
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=self._config.timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            details = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(details[-4000:] or "Core Backend scenario failed")
        return result.stdout

    @staticmethod
    def _new_run_id(payment: str) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"qa-fm-{payment.lower()}-{timestamp}-{uuid4().hex[:8]}"


def _scenario_script(payment: str, shop_id: str, run_id: str) -> str:
    client_phone = os.environ["FM_TEST_CLIENT_PHONE"].lstrip("+")
    method = SCENARIO_METHODS[payment]
    extra_args = ""
    setup = ""
    if payment == "PAYLER":
        setup = "delivery_service, delivery_type = builder._create_delivery(shop)\n"
        extra_args = ", delivery_type"
    return f"""
import json
from django.contrib.auth import get_user_model
from apps.category.models import Category
from apps.order.choices import OrderStatusChoices
from apps.order.management.commands.trigger_finmodule_debezium_flows import _FinmoduleDebeziumFlowBuilder
from apps.order.models import Order
from django.utils import timezone

builder = _FinmoduleDebeziumFlowBuilder(run_id={run_id!r}, shop_id={int(shop_id)})
User = get_user_model()
client = User.objects.get(
    phone_number__in={[client_phone, "+" + client_phone]!r}, is_active=True, user_type=User.TYPE_CUSTOMER
)
shop = builder._get_existing_shop()
if str(shop.external_id) != {os.environ["FM_TEST_MERCHANT_ID"]!r}:
    raise RuntimeError("Shop does not belong to the configured test merchant")
category = Category.objects.create(name=f"FM Debezium Category {{builder.safe_run_id}}")
{setup}flow = builder.{method}(client, shop, category{extra_args})
Order.objects.filter(id=flow["order_id"], is_test=True).update(
    is_paid=True,
    status=OrderStatusChoices.STATUS_INITIALIZED,
    order_status_time=timezone.now(),
)
print("QA_SCENARIO_JSON=" + json.dumps({{
    "payment": {payment!r},
    "run_id": builder.run_id,
    "shop": {{"id": shop.id, "external_id": str(shop.external_id)}},
    "flow": flow,
}}, ensure_ascii=False))
"""


def _completion_script(scenario: CreatedOrderScenario) -> str:
    return f"""
from apps.order.choices import OrderStatusChoices, OrderStatusHistorySourceChoices
from apps.order.models import Order
from django.utils import timezone

completed_at = timezone.now()
updated = Order.objects.filter(
    id={int(scenario.order_id)},
    shop_id={int(scenario.shop_id)},
    is_test=True,
    is_paid=True,
    status=OrderStatusChoices.STATUS_INITIALIZED,
).update(
    status=OrderStatusChoices.STATUS_DELIVERED,
    delivery_time=completed_at,
    order_status_time=completed_at,
    status_history_source=OrderStatusHistorySourceChoices.SYSTEM,
    status_history_user_id=None,
)
print(f"QA_ORDER_COMPLETED={{updated}}")
"""


def _extract_summary(stdout: str) -> dict:
    marker = "QA_SCENARIO_JSON="
    for line in reversed(stdout.splitlines()):
        if line.startswith(marker):
            return json.loads(line.removeprefix(marker))
    raise RuntimeError("Core Backend scenario did not return a JSON summary")


def _build_scenario(summary: dict) -> CreatedOrderScenario:
    payment = str(summary["payment"])
    flow = summary["flow"]
    shop = summary["shop"]
    provider_reference = flow.get("provider_reference")
    if not provider_reference:
        raise RuntimeError(f"Scenario {payment} has no provider_reference")
    return CreatedOrderScenario(
        payment=payment,
        run_id=str(summary["run_id"]),
        order_id=str(flow["order_id"]),
        order_code=str(flow["order_code"]),
        provider_reference=str(provider_reference),
        merchant_id=str(shop["external_id"]),
        shop_id=str(shop["id"]),
        total_sum=Decimal(str(flow["total_sum"])),
        finance_payment_method=FINANCE_PAYMENT_METHODS[payment],
        installment_plan=INSTALLMENT_PLANS[payment],
    )
