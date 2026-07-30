from __future__ import annotations

import os

import pytest

from finance_autotests.config import Settings
from finance_autotests.database import FinanceDatabase
from finance_autotests.kafka import KafkaPublisher


@pytest.fixture(scope="session")
def settings() -> Settings:
    allow_side_effects = os.getenv("FM_ALLOW_SIDE_EFFECTS", "").strip().lower()
    if allow_side_effects not in {"1", "true", "yes", "on"}:
        pytest.skip(
            "Внешние тесты отключены. Для QA-стенда задайте "
            "FM_ALLOW_SIDE_EFFECTS=true"
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
def kafka(settings: Settings) -> KafkaPublisher:
    return KafkaPublisher(
        brokers=settings.kafka_brokers,
        security_protocol=settings.kafka_security_protocol,
        sasl_mechanism=settings.kafka_sasl_mechanism,
        username=settings.kafka_username,
        password=settings.kafka_password,
    )
