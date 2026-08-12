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
            yield connection

    def _one(self, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                return cursor.fetchone()

    def _many(self, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                return list(cursor.fetchall())

    def merchant_job(self, merchant_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT id, merchant_id, status, progress, retry_count, last_error
            FROM merchant_jobs
            WHERE merchant_id = %s
            """,
            (merchant_id,),
        )

    def merchant_accounts(self, merchant_id: str) -> list[dict[str, Any]]:
        return self._many(
            """
            SELECT merchant_id, account_type, balance_id, ledger_id
            FROM merchant_accounts
            WHERE merchant_id = %s
            ORDER BY account_type
            """,
            (merchant_id,),
        )

    def payment_job(self, payment_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT
                id, order_id, payment_id, amount, currency,
                payment_method, installment_months,
                status, progress, retry_count, last_error,
                credit_txn_id, credited_at, split_at
            FROM payment_jobs
            WHERE payment_id = %s
            """,
            (payment_id,),
        )

    def payment_job_count(self, payment_id: str) -> int:
        row = self._one(
            "SELECT COUNT(*) AS count FROM payment_jobs WHERE payment_id = %s",
            (payment_id,),
        )
        return int(row["count"]) if row else 0

    def completion_intent(self, order_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT order_id, event_type, processed, processed_at
            FROM order_completion_intents
            WHERE order_id = %s
            """,
            (order_id,),
        )

    def snapshot(self, payment_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT id, order_id, payment_id, total_amount, currency
            FROM payment_order_snapshots
            WHERE payment_id = %s
            """,
            (payment_id,),
        )

    def snapshot_items(self, payment_id: str) -> list[dict[str, Any]]:
        return self._many(
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

    def order_transactions(self, payment_id: str) -> list[dict[str, Any]]:
        return self._many(
            """
            SELECT
                transaction_type, amount, blnk_transaction_id,
                merchant_id, order_item_id, metadata
            FROM order_transactions
            WHERE payment_id = %s
            ORDER BY created_at, id
            """,
            (payment_id,),
        )

    def order_transaction_count(self, payment_id: str, transaction_type: str) -> int:
        row = self._one(
            """
            SELECT COUNT(*) AS count
            FROM order_transactions
            WHERE payment_id = %s AND transaction_type = %s
            """,
            (payment_id, transaction_type),
        )
        return int(row["count"]) if row else 0

    def monitoring_jobs(
        self,
        payment_id: str,
        operation_type: str,
    ) -> list[dict[str, Any]]:
        return self._many(
            """
            SELECT
                id, operation_type, external_transaction_id,
                reference, blnk_transaction_id, status, blnk_status,
                retry_count, last_error, finalized_at
            FROM transaction_status_monitoring_jobs
            WHERE external_transaction_id = %s
              AND operation_type = %s
            ORDER BY created_at, id
            """,
            (payment_id, operation_type),
        )

    @staticmethod
    def amount(value: Any) -> Decimal:
        return Decimal(str(value))
