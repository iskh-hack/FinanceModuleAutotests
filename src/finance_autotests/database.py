from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Iterator


class FinanceDatabase:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(
            self._dsn,
            autocommit=True,
            row_factory=dict_row,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET default_transaction_read_only = on")
            yield connection

    def payment_job(self, payment_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id, order_id, payment_id, amount, currency,
                        status, retry_count, last_error
                    FROM payment_jobs
                    WHERE payment_id = %s
                    """,
                    (payment_id,),
                )
                return cursor.fetchone()

    def snapshot(self, payment_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, order_id, payment_id, total_amount, currency
                    FROM payment_order_snapshots
                    WHERE payment_id = %s
                    """,
                    (payment_id,),
                )
                return cursor.fetchone()

    def snapshot_items(self, payment_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        order_item_id, merchant_id, product_id,
                        category_id, item_total
                    FROM payment_order_snapshot_items
                    WHERE payment_id = %s
                    ORDER BY created_at, id
                    """,
                    (payment_id,),
                )
                return list(cursor.fetchall())

    @staticmethod
    def amount(value: Any) -> Decimal:
        return Decimal(str(value))

