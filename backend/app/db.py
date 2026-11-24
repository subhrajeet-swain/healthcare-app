"""Every data access runs inside tenant_tx: one transaction with SET LOCAL app.tenant_id."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.tenancy import TenantCtx

_pool: ConnectionPool | None = None


def init_pool(url: str, max_size: int = 10) -> None:
    global _pool
    close_pool()
    _pool = ConnectionPool(
        url, min_size=1, max_size=max_size, kwargs={"row_factory": dict_row}, open=True
    )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("db pool not initialised")
    return _pool


def _set_tenant(conn: psycopg.Connection, tenant_id: UUID) -> None:
    # is_local=true: reverts at transaction end, so a pooled connection never keeps it.
    conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))


@contextmanager
def tenant_tx(ctx: TenantCtx) -> Iterator[psycopg.Connection]:
    with pool().connection() as conn:  # commits on success, rolls back on exception
        _set_tenant(conn, ctx.tenant_id)
        yield conn


@contextmanager
def owner_tx(url: str, tenant_id: UUID | None = None) -> Iterator[psycopg.Connection]:
    """Owner-role transaction for migrations, provisioning, seed and tests."""
    with psycopg.connect(url, row_factory=dict_row) as conn:
        if tenant_id is not None:
            _set_tenant(conn, tenant_id)
        yield conn
