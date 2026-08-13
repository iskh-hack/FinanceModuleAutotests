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
    retry_exceptions: tuple[type[Exception], ...] = (),
) -> T:
    deadline = time.monotonic() + timeout
    last_value: T | None = None
    last_error: Exception | None = None

    while True:
        try:
            last_value = operation()
            last_error = None
        except retry_exceptions as error:
            last_error = error
        if last_value is not None:
            return last_value
        if time.monotonic() >= deadline:
            details = (
                f" Последняя временная ошибка: {last_error!r}"
                if last_error is not None
                else ""
            )
            raise TimeoutError(
                f"Не дождались: {description}. Последнее значение: "
                f"{last_value!r}.{details}"
            )
        time.sleep(interval)
