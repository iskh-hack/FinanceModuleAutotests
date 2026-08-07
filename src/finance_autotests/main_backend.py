from __future__ import annotations

import base64
import json
import subprocess
import time
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
        stdout = self._run_shell(
            self._fixture_code(
                run_id=run_id,
                shop_id=shop_id,
                client_phone=client_phone,
            )
        )
        return MbankOrderFixture(**self._parse_result(stdout))

    def complete_order(self, order_id: str) -> None:
        if not order_id.isdigit():
            raise ValueError("order_id должен быть числовым")
        code = f"""
from django.utils import timezone
from apps.order.choices import OrderStatusChoices, OrderStatusHistorySourceChoices
from apps.order.models import Order

order_id = {int(order_id)!r}
updated = Order.objects.filter(id=order_id, is_test=True).update(
    status=OrderStatusChoices.STATUS_COLLECT,
    is_paid=True,
)
if updated != 1:
    raise RuntimeError("Тестовый Order не найден")
Order.objects.filter(id=order_id).update(
    status=OrderStatusChoices.STATUS_DELIVERED,
    delivery_time=timezone.now(),
    status_history_source=OrderStatusHistorySourceChoices.SYSTEM,
    status_history_user_id=None,
)
print("{RESULT_MARKER}completed")
"""
        stdout = self._run_shell(code)
        if RESULT_MARKER + "completed" not in stdout:
            raise RuntimeError("Main Backend не подтвердил завершение Order")

    def _run_shell(self, code: str, timeout: float = 180) -> str:
        # Rancher proxy обрывает долгий kubectl exec примерно через 30 секунд.
        # Запускаем Django shell в pod асинхронно и опрашиваем короткими exec.
        execution_id = f"fm-autotest-{uuid4().hex}"
        prefix = f"/tmp/{execution_id}"
        encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
        launch = (
            f"if mkdir {prefix}.lock 2>/dev/null; then "
            f"echo {encoded} | base64 -d > {prefix}.py; "
            f"nohup sh -c 'python manage.py shell -c \"$(cat {prefix}.py)\" "
            f"> {prefix}.out 2>&1; echo $? > {prefix}.exit' "
            "> /dev/null 2>&1 < /dev/null & fi"
        )
        resource = self._resolve_resource()
        launch_error = ""
        for _ in range(5):
            result = self._exec(resource, ["sh", "-c", launch])
            if result.returncode == 0:
                break
            launch_error = (result.stderr or result.stdout).strip()
            started = self._exec(resource, ["test", "-d", f"{prefix}.lock"])
            if started.returncode == 0:
                break
            time.sleep(2)
        else:
            raise RuntimeError(launch_error[-8000:])

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            poll = self._exec(
                resource,
                ["sh", "-c", f"test -f {prefix}.exit && cat {prefix}.exit"],
            )
            if poll.returncode == 0 and poll.stdout.strip():
                output = self._read_remote_file(resource, f"{prefix}.out")
                self._exec(
                    resource,
                    [
                        "sh",
                        "-c",
                        f"rm -f {prefix}.py {prefix}.out {prefix}.exit; "
                        f"rmdir {prefix}.lock",
                    ],
                )
                if poll.stdout.strip() != "0":
                    raise RuntimeError(
                        "Main Backend fixture завершилась с ошибкой:\n"
                        + (output.stdout or output.stderr).strip()[-8000:]
                    )
                return output.stdout
            time.sleep(2)
        raise TimeoutError("Main Backend fixture не завершилась за 180 секунд")

    def _read_remote_file(self, resource: str, path: str):
        last_result = None
        for _ in range(5):
            last_result = self._exec(resource, ["cat", path])
            if last_result.returncode == 0:
                return last_result
            time.sleep(2)
        details = (last_result.stderr or last_result.stdout).strip()
        raise RuntimeError("Не удалось прочитать результат из pod:\n" + details[-8000:])

    def _exec(self, resource: str, remote_command: list[str]):
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
                resource,
                "-c",
                self._container,
                "--",
                *remote_command,
            ]
        )
        try:
            return subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=25,
            )
        except subprocess.TimeoutExpired as error:
            return subprocess.CompletedProcess(
                command,
                124,
                stdout=error.stdout or "",
                stderr="kubectl exec не ответил за 25 секунд",
            )

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
            timeout=30,
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
