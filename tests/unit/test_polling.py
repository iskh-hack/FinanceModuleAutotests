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

