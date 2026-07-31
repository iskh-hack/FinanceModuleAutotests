from __future__ import annotations

import os

import pytest

from finance_autotests.config import Settings
from finance_autotests.database import FinanceDatabase
from finance_autotests.main_backend import MainBackendFixtureFactory


@pytest.fixture(scope="session")
def settings() -> Settings:
    allow_side_effects = os.getenv("FM_ALLOW_SIDE_EFFECTS", "").strip().lower()
    downstream_isolated = os.getenv(
        "FM_CONFIRM_DOWNSTREAM_ISOLATED", ""
    ).strip().lower()
    if allow_side_effects not in {"1", "true", "yes", "on"}:
        pytest.skip(
            "Внешние тесты отключены. Для QA-стенда задайте "
            "FM_ALLOW_SIDE_EFFECTS=true"
        )
    if downstream_isolated not in {"1", "true", "yes", "on"}:
        pytest.skip(
            "Не подтверждена изоляция Blnk/MBonus: задайте "
            "FM_CONFIRM_DOWNSTREAM_ISOLATED=true только для безопасного стенда"
        )
    try:
        result = Settings.from_env()
    except ValueError as error:
        pytest.skip(str(error))
    return result


@pytest.fixture(scope="session")
def finance_db(settings: Settings) -> FinanceDatabase:
    return FinanceDatabase(settings.postgres_dsn)


@pytest.fixture(scope="session")
def main_backend(settings: Settings) -> MainBackendFixtureFactory:
    return MainBackendFixtureFactory(
        kubectl_path=settings.kubectl_path,
        kubeconfig_path=settings.kubeconfig_path,
        namespace=settings.kube_namespace,
        resource=settings.main_backend_resource,
        container=settings.main_backend_container,
        insecure_skip_tls_verify=settings.kube_insecure_skip_tls_verify,
    )
