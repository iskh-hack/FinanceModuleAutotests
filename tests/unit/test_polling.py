import pytest

from finance_autotests.polling import wait_for


def test_wait_for_returns_first_non_none_value() -> None:
    values = iter([None, None, {"status": "ready"}])

    result = wait_for(
        lambda: next(values),
        timeout=1,
        interval=0,
        description="готовое состояние",
    )

    assert result == {"status": "ready"}


def test_wait_for_raises_clear_timeout() -> None:
    with pytest.raises(TimeoutError, match="payment_job"):
        wait_for(
            lambda: None,
            timeout=0,
            interval=0,
            description="payment_job",
        )


def test_wait_for_retries_only_declared_transient_error() -> None:
    class TemporaryConnectionError(Exception):
        pass

    attempts = iter(
        [TemporaryConnectionError("connection closed"), {"status": "ready"}]
    )

    def operation():
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        return result

    assert wait_for(
        operation,
        timeout=1,
        interval=0,
        description="восстановление соединения",
        retry_exceptions=(TemporaryConnectionError,),
    ) == {"status": "ready"}


def test_wait_for_does_not_hide_unexpected_error() -> None:
    with pytest.raises(ValueError, match="bad query"):
        wait_for(
            lambda: (_ for _ in ()).throw(ValueError("bad query")),
            timeout=1,
            interval=0,
            description="SQL",
            retry_exceptions=(ConnectionError,),
        )
