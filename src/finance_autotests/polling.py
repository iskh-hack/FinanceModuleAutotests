from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def wait_for(
    operation: Callable[[], T | None],
    *,
    timeout: float,
    interval: float,
    description: str,
) -> T:
    deadline = time.monotonic() + timeout
    last_value: T | None = None

    while True:
        last_value = operation()
        if last_value is not None:
            return last_value
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Не дождались: {description}. Последнее значение: {last_value!r}"
            )
        time.sleep(interval)

