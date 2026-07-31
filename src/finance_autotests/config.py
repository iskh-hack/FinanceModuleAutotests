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
    downstream_isolated: bool
    kubectl_path: str
    kubeconfig_path: str
    kube_insecure_skip_tls_verify: bool
    kube_namespace: str
    main_backend_resource: str
    main_backend_container: str
    postgres_dsn: str
    test_shop_id: int
    test_client_phone: str
    wait_timeout_seconds: float
    wait_interval_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            allow_side_effects=_as_bool(os.getenv("FM_ALLOW_SIDE_EFFECTS")),
            downstream_isolated=_as_bool(
                os.getenv("FM_CONFIRM_DOWNSTREAM_ISOLATED")
            ),
            kubectl_path=os.getenv("FM_KUBECTL_PATH", "kubectl").strip(),
            kubeconfig_path=_required("FM_KUBECONFIG"),
            kube_insecure_skip_tls_verify=_as_bool(
                os.getenv("FM_KUBE_INSECURE_SKIP_TLS_VERIFY")
            ),
            kube_namespace=os.getenv("FM_KUBE_NAMESPACE", "market").strip(),
            main_backend_resource=os.getenv(
                "FM_MAIN_BACKEND_RESOURCE",
                "auto",
            ).strip(),
            main_backend_container=os.getenv(
                "FM_MAIN_BACKEND_CONTAINER",
                "service-market-core-backend-api",
            ).strip(),
            postgres_dsn=_required("FM_POSTGRES_DSN"),
            test_shop_id=int(_required("FM_TEST_SHOP_ID")),
            test_client_phone=_required("FM_TEST_CLIENT_PHONE").removeprefix(
                "+"
            ),
            wait_timeout_seconds=float(
                os.getenv("FM_WAIT_TIMEOUT_SECONDS", "120")
            ),
            wait_interval_seconds=float(
                os.getenv("FM_WAIT_INTERVAL_SECONDS", "2")
            ),
        )
