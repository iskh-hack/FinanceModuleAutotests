from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from uuid import uuid4


RESULT_MARKER = "__FM_AUTOTEST_RESULT__="


@dataclass(frozen=True)
class MbankOrderFixture:
    order_id: str
    payment_id: str
    order_item_id: str
    product_id: str
    category_id: str
    shop_id: str
    merchant_id: str
    provider_reference: str
    total_amount: str


class MainBackendFixtureFactory:
    def __init__(
        self,
        *,
        kubectl_path: str,
        kubeconfig_path: str,
        namespace: str,
        resource: str,
        container: str,
        insecure_skip_tls_verify: bool,
    ) -> None:
        self._kubectl_path = kubectl_path
        self._kubeconfig_path = kubeconfig_path
        self._namespace = namespace
        self._resource = resource
        self._container = container
        self._insecure_skip_tls_verify = insecure_skip_tls_verify

    def create_mbank_order(
        self,
        *,
        shop_id: int,
        client_phone: str,
    ) -> MbankOrderFixture:
        run_id = f"qa-smoke-{uuid4().hex[:16]}"
        command = [
            self._kubectl_path,
            "--kubeconfig",
            self._kubeconfig_path,
        ]
        if self._insecure_skip_tls_verify:
            command.append("--insecure-skip-tls-verify=true")
        command.extend(
            [
                "-n",
                self._namespace,
                "exec",
                self._resolve_resource(),
                "-c",
                self._container,
                "--",
                "python",
                "manage.py",
                "shell",
                "-c",
                self._fixture_code(
                    run_id=run_id,
                    shop_id=shop_id,
                    client_phone=client_phone,
                ),
            ]
        )
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            details = (result.stderr or result.stdout).strip()
            raise RuntimeError(
                "Main Backend fixture завершилась с ошибкой:\n"
                + details[-8000:]
            )
        return MbankOrderFixture(**self._parse_result(result.stdout))

    def _resolve_resource(self) -> str:
        if self._resource != "auto":
            return self._resource

        command = [
            self._kubectl_path,
            "--kubeconfig",
            self._kubeconfig_path,
        ]
        if self._insecure_skip_tls_verify:
            command.append("--insecure-skip-tls-verify=true")
        command.extend(["-n", self._namespace, "get", "pods", "-o", "json"])
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Не удалось получить pods Main Backend:\n"
                + (result.stderr or result.stdout).strip()[-4000:]
            )

        candidates = []
        for pod in json.loads(result.stdout)["items"]:
            name = pod["metadata"]["name"]
            containers = {
                item["name"] for item in pod["spec"].get("containers", [])
            }
            statuses = pod.get("status", {}).get("containerStatuses", [])
            if (
                name.startswith("service-market-core-backend-api-")
                and self._container in containers
                and pod.get("status", {}).get("phase") == "Running"
                and any(
                    item["name"] == self._container and item.get("ready")
                    for item in statuses
                )
            ):
                candidates.append(
                    (pod.get("status", {}).get("startTime", ""), name)
                )
        if not candidates:
            raise RuntimeError("Не найден готовый pod Main Backend")
        _, name = max(candidates)
        return f"pod/{name}"

    @staticmethod
    def _parse_result(stdout: str) -> dict[str, str]:
        for line in reversed(stdout.splitlines()):
            if line.startswith(RESULT_MARKER):
                return json.loads(line.removeprefix(RESULT_MARKER))
        raise RuntimeError(
            "Main Backend не вернул маркер результата тестового заказа"
        )

    @staticmethod
    def _fixture_code(
        *,
        run_id: str,
        shop_id: int,
        client_phone: str,
    ) -> str:
        # Штатный builder создаёт реальные Order/Product/OrderProduct/
        # Transaction. Debezium и producer сами формируют order.paid.
        return f"""
import json
from django.db import models, transaction
from apps.category.models import Category
from apps.order.choices import OrderPaymentMethodChoices
from apps.order.kafka.handlers.utils import generate_idempotency_key
from apps.order.management.commands.trigger_finmodule_debezium_flows import _FinmoduleDebeziumFlowBuilder
from apps.order.models import Order, OrderProduct, Transaction
from apps.user.models import User

run_id = {run_id!r}
shop_id = {shop_id!r}
client_phone = {client_phone!r}
user = User.objects.filter(
    phone_number__in=[client_phone, "+" + client_phone],
    is_active=True,
    user_type=User.TYPE_CUSTOMER,
).first()
if user is None:
    raise RuntimeError("Активный тестовый customer не найден")

# Схема market-dev содержит refund_status, но поле отсутствует в модели
# текущего Main Backend image. Добавляем его только в процесс shell.
if not hasattr(Order, "refund_status"):
    models.CharField(max_length=16, default="none").contribute_to_class(
        Order, "refund_status"
    )
if not hasattr(Order, "remainder_reminder_sent"):
    models.BooleanField(default=False).contribute_to_class(
        Order, "remainder_reminder_sent"
    )

with transaction.atomic():
    builder = _FinmoduleDebeziumFlowBuilder(run_id=run_id, shop_id=shop_id)
    shop = builder._get_existing_shop()
    if not shop.is_test:
        raise RuntimeError("Smoke разрешён только для Shop с is_test=True")
    category = Category.objects.create(name=f"FM QA Smoke {{run_id}}")
    summary = builder._create_mbank_native_flow(user, shop, category)
    order_id = summary["order_id"]
    transaction_record = Transaction.objects.filter(
        order_id=order_id
    ).latest("id")
    order_item = OrderProduct.objects.select_related(
        "order", "product__shop", "product__category"
    ).get(order_id=order_id)
    payment_type = OrderPaymentMethodChoices.MBANK.value
    provider_reference = str(transaction_record.qid)
    result = {{
        "order_id": str(order_id),
        "payment_id": generate_idempotency_key(
            order_id, provider_reference, payment_type
        ),
        "order_item_id": str(order_item.id),
        "product_id": str(order_item.product_id),
        "category_id": str(order_item.product.category_id),
        "shop_id": str(order_item.product.shop_id),
        "merchant_id": str(order_item.product.shop.external_id),
        "provider_reference": provider_reference,
        "total_amount": str(order_item.order.total_sum),
    }}
print({RESULT_MARKER!r} + json.dumps(result))
"""
