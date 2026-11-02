from __future__ import annotations

from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class StoreError(Exception):
    status_code = 400


class NotFoundError(StoreError):
    status_code = 404


class ConflictError(StoreError):
    status_code = 409


class TransactionPool:
    """Let domain stores reuse a caller's already scoped transaction."""
    def __init__(self, conn):
        self.conn = conn

    @contextmanager
    def connection(self):
        yield self.conn


def create_pool(database_url: str) -> ConnectionPool:
    return ConnectionPool(
        conninfo=database_url,
        min_size=1,
        max_size=5,
        timeout=10,
        open=False,
        kwargs={"row_factory": dict_row},
    )


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(value) for value in values) + "]"
