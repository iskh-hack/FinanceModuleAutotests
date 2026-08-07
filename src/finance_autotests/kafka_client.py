from __future__ import annotations

import json
from typing import Any


class KafkaPublisher:
    def __init__(self, bootstrap_servers: str) -> None:
        from kafka import KafkaProducer

        self._producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda value: json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
            acks="all",
        )

    def publish(self, topic: str, event: dict[str, Any]) -> None:
        self._producer.send(topic, value=event).get(timeout=20)
        self._producer.flush(timeout=20)

    def close(self) -> None:
        self._producer.close(timeout=20)

    def __enter__(self) -> "KafkaPublisher":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
