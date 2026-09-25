from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import requests

from .core_backend import CreatedOrderScenario, FINANCE_PAYMENT_METHODS, INSTALLMENT_PLANS
from .polling import wait_for

PAID_STATUSES = {"INITIALIZED", "COLLECT", "READY", "READY_TO_SHIP", "COLLECTING_BRANCHES", "DELIVERED"}
FAILED_STATUSES = {"CANCELLED"}

MBANK_OP_CHECK = "QE11"
MBANK_OP_PAYMENT = "QE10"
MBANK_STATUS_CHECK_OK = "200"
MBANK_STATUS_PAID = "250"

PICKUP_ENDPOINTS = {"pvz": "get_pvzs", "pickuppoint": "get_pick_up_points", "shop": "get_branches"}


class MarketCheckoutError(RuntimeError):
    """A step of the real Market client checkout flow failed."""


@dataclass(frozen=True)
class MarketCheckoutConfig:
    base_url: str
    client_phone: str
    dev_login_token: str
    webhook_token: str
    product_id: str
    merchant_id: str
    shop_id: str
    timeout_seconds: int = 60
    poll_timeout_seconds: float = 120
    poll_interval_seconds: float = 3


class MarketCheckoutFactory:
    """Create one real MBANK order through the deployed Market client HTTP API."""

    def __init__(self, config: MarketCheckoutConfig) -> None:
        self._config = config
        self._headers: dict[str, str] = {}

    def create(self, *, payment: str = "MBANK") -> CreatedOrderScenario:
        payment_key = payment.strip().upper()
        if payment_key != "MBANK":
            raise ValueError(f"MarketCheckoutFactory currently supports only MBANK, got {payment!r}")

        self._login()
        order_id = self._add_to_cart()
        self._set_pickup_delivery(order_id)
        prepare = self._prepare_order(order_id)
        provider_reference = self._pay_with_mbank(order_id, prepare)
        self._wait_paid(order_id)

        return CreatedOrderScenario(
            payment=payment_key,
            run_id=f"qa-market-{order_id}",
            order_id=str(order_id),
            order_code=str(order_id),
            provider_reference=provider_reference,
            merchant_id=self._config.merchant_id,
            shop_id=self._config.shop_id,
            total_sum=Decimal(str(prepare["totalAmount"])),
            finance_payment_method=FINANCE_PAYMENT_METHODS[payment_key],
            installment_plan=INSTALLMENT_PLANS[payment_key],
        )

    def complete(self, scenario: CreatedOrderScenario) -> None:
        """Move the order to DELIVERED through the real dispatcher API (requires Dispatcher role)."""
        self._login()
        self._call(
            "PATCH",
            f"/api/crm/dispatcher/v2/orders/{scenario.order_id}/",
            payload={"status": "DELIVERED"},
        )

    # -- steps --

    def _login(self) -> None:
        phone_digits = self._config.client_phone.lstrip("+")
        body = self._call(
            "POST",
            "/api/users/mbankAuth/",
            payload={"token": f"{self._config.dev_login_token}+{phone_digits}"},
        )
        access = body.get("token") if isinstance(body, dict) else None
        if not access:
            raise MarketCheckoutError(f"Dev login response has no token: {body!r}")
        self._headers["Authorization"] = f"Bearer {access}"

    def _add_to_cart(self) -> int:
        body = self._call(
            "POST", "/api/cartProduct/", payload={"product": int(self._config.product_id), "quantity": 1}
        )
        order_id = _int_field(body, ("pk", "id", "order_id", "cart_id"))
        if order_id is None:
            raise MarketCheckoutError(f"Cart response has no id: {body!r}")
        return order_id

    def _set_pickup_delivery(self, order_id: int) -> None:
        self._call("POST", f"/api/cart/{order_id}/set_delivery_method/", payload={"delivery_method": "pickup"})
        for kind, endpoint in PICKUP_ENDPOINTS.items():
            for point in _as_list(self._call("GET", f"/api/cart/{order_id}/{endpoint}/")):
                point_id = point.get("id")
                if not point_id or point.get("is_available") is False:
                    continue
                self._call(
                    "POST",
                    f"/api/cart/{order_id}/set_pick_up_point/",
                    payload={"pick_up_from": kind, "self_delivery_point_id": point_id},
                )
                return
        raise MarketCheckoutError(f"No available pickup point for cart {order_id}")

    def _prepare_order(self, order_id: int) -> dict[str, Any]:
        prepare = self._call(
            "POST",
            "/api/order/prepare/",
            payload={
                "order_id": order_id,
                "receiver_first_name": "QA",
                "receiver_last_name": "Autotest",
                "phone_to_call": f"+{self._config.client_phone.lstrip('+')}",
                "delivery_method": "pickup",
                "do_not_call": False,
            },
        )
        if not isinstance(prepare, dict) or not prepare.get("totalAmount"):
            raise MarketCheckoutError(f"order/prepare has no totalAmount: {prepare!r}")
        return prepare

    def _pay_with_mbank(self, order_id: int, prepare: dict[str, Any]) -> str:
        service_id = str(prepare.get("paymentTreeServiceId") or "")
        if not service_id:
            raise MarketCheckoutError(f"order/prepare has no paymentTreeServiceId: {prepare!r}")
        amount = str(prepare["totalAmount"])
        qid = str(uuid.uuid4())

        check_body = self._mbank_call(self._mbank_xml(MBANK_OP_CHECK, qid, order_id, service_id))
        if check_body.get("STATUS") != MBANK_STATUS_CHECK_OK:
            raise MarketCheckoutError(f"MBank QE11 rejected: {check_body!r}")

        confirmed_amount = check_body.get("SUM") or amount
        pay_body = self._mbank_call(self._mbank_xml(MBANK_OP_PAYMENT, qid, order_id, service_id, confirmed_amount))
        if pay_body.get("STATUS") != MBANK_STATUS_PAID:
            raise MarketCheckoutError(f"MBank QE10 rejected: {pay_body!r}")
        return qid

    def _wait_paid(self, order_id: int) -> str:
        def poll() -> str | None:
            body = self._call("GET", f"/api/order/{order_id}/get_order_status/")
            status = body.get("status") if isinstance(body, dict) else None
            if status in FAILED_STATUSES:
                raise MarketCheckoutError(f"Order {order_id} moved to {status} instead of paid")
            return status if status in PAID_STATUSES else None

        return wait_for(
            poll,
            timeout=self._config.poll_timeout_seconds,
            interval=self._config.poll_interval_seconds,
            description=f"paid status for order {order_id}",
        )

    # -- http/xml plumbing --

    def _call(self, method: str, path: str, *, payload: dict | None = None) -> Any:
        url = f"{self._config.base_url.rstrip('/')}{path}"
        response = requests.request(
            method, url, json=payload, headers=self._headers, timeout=self._config.timeout_seconds
        )
        try:
            body = response.json()
        except ValueError:
            body = response.text
        if response.status_code not in (200, 201, 204):
            raise MarketCheckoutError(f"{method} {path} returned {response.status_code}: {body!r}")
        return body

    def _mbank_xml(self, operation: str, qid: str, order_id: int, service_id: str, amount: str | None = None) -> str:
        body = f'SERVICE_ID="{service_id}" PARAM1="{order_id}"'
        if amount is not None:
            body += f' SUM="{amount}"'
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n<XML>\n'
            f'<HEAD DTS="{datetime.now():%Y-%m-%d %H:%M:%S}" QM="1" QID="{qid}" OP="{operation}" />\n'
            f"<BODY {body} />\n</XML>"
        )

    def _mbank_call(self, xml_payload: str) -> dict[str, str]:
        url = f"{self._config.base_url.rstrip('/')}/api/mbank/mbankPayment/"
        response = requests.post(
            url,
            params={"token": self._config.webhook_token},
            data=xml_payload.encode("utf-8"),
            headers={"Content-Type": "application/xml"},
            timeout=self._config.timeout_seconds,
        )
        if response.status_code != 200:
            raise MarketCheckoutError(f"MBank webhook returned {response.status_code}: {response.text[:400]!r}")
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as error:
            raise MarketCheckoutError(f"MBank webhook returned non-XML: {response.text[:400]!r}") from error
        parsed = {child.tag: child.attrib for child in root}
        return parsed.get("BODY", {})


def _as_list(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("results", "data", "items"):
            if isinstance(body.get(key), list):
                return body[key]
    return []


def _int_field(body: Any, keys: tuple[str, ...]) -> int | None:
    if isinstance(body, dict):
        for key in keys:
            value = body.get(key)
            if isinstance(value, int):
                return value
    return None
