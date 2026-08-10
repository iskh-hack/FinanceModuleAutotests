from __future__ import annotations

import json
from typing import Any

from finance_autotests.events import KafkaMessage


class KafkaPublisher:
    def __init__(self, bootstrap_servers: str) -> None:
        from kafka import KafkaProducer

        self._producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            key_serializer=lambda value: value.encode("utf-8"),
            value_serializer=lambda value: json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
            acks="all",
        )

    def publish(self, topic: str, event: dict[str, Any], *, key: str | None = None) -> None:
        self._producer.send(topic, key=key, value=event).get(timeout=20)
        self._producer.flush(timeout=20)

    def publish_message(self, message: KafkaMessage) -> None:
        self.publish(message.topic, message.value, key=message.key)

    def close(self) -> None:
        self._producer.close(timeout=20)

    def __enter__(self) -> "KafkaPublisher":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
