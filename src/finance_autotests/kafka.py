from __future__ import annotations

import json
from typing import Any


class KafkaPublisher:
    def __init__(
        self,
        *,
        brokers: str,
        security_protocol: str,
        sasl_mechanism: str,
        username: str,
        password: str,
    ) -> None:
        from confluent_kafka import Producer

        config: dict[str, Any] = {
            "bootstrap.servers": brokers,
            "security.protocol": security_protocol,
            "client.id": "finance-module-qa-autotests",
            "enable.idempotence": True,
        }
        if security_protocol.upper().startswith("SASL"):
            if not username or not password:
                raise ValueError(
                    "Для SASL Kafka необходимы username и password"
                )
            config["sasl.username"] = username
            config["sasl.password"] = password
            config["sasl.mechanism"] = sasl_mechanism
        self._producer = Producer(config)

    def publish_json(
        self,
        *,
        topic: str,
        key: str,
        payload: dict[str, Any],
        timeout: float = 15,
    ) -> None:
        delivery_error: list[Exception] = []

        def on_delivery(error: Any, _message: Any) -> None:
            if error is not None:
                delivery_error.append(RuntimeError(str(error)))

        self._producer.produce(
            topic=topic,
            key=key.encode("utf-8"),
            value=json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8"),
            on_delivery=on_delivery,
        )
        remaining = self._producer.flush(timeout)
        if remaining:
            raise TimeoutError(
                f"Kafka не подтвердил отправку {remaining} сообщений"
            )
        if delivery_error:
            raise delivery_error[0]
