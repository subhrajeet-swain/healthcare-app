import uuid

import psycopg
import pytest

from app import db
from app.tenancy import TenantCtx


@pytest.fixture
def pool1(db_urls):
    """A one-connection pool, so every checkout reuses the same physical connection."""
    db.init_pool(db_urls["app"], max_size=1)
    yield
    db.close_pool()


@pytest.fixture
def two_tenants(db_urls):
    ids = {}
    for name in ("a", "b"):
        with db.owner_tx(db_urls["owner"]) as c:
            tid = c.execute(
                "INSERT INTO tenants (slug, name) VALUES (%s, %s) RETURNING id",
                (f"t-{name}-{uuid.uuid4().hex[:8]}", name),
            ).fetchone()["id"]
        with db.owner_tx(db_urls["owner"], tid) as c:
            uid = c.execute(
                "INSERT INTO users (tenant_id, role, phone_fp, phone_enc) "
                "VALUES (%s, 'patient', %s, %s) RETURNING id",
                (tid, uuid.uuid4().bytes, b"x"),
            ).fetchone()["id"]
        ids[name] = (tid, uid)
    return ids


def test_tenant_sees_only_own_rows(pool1, two_tenants):
    tid_a, _ = two_tenants["a"]
    with db.tenant_tx(TenantCtx(tid_a)) as c:
        rows = c.execute("SELECT tenant_id FROM users").fetchall()
    assert len(rows) == 1
    assert rows[0]["tenant_id"] == tid_a


def test_query_without_tenant_raises(pool1, two_tenants):
    with pytest.raises(psycopg.Error):
        with db.pool().connection() as c:
            c.execute("SELECT * FROM users").fetchall()


def test_reused_connection_after_tenant_tx_raises(pool1, two_tenants):
    tid_a, _ = two_tenants["a"]
    with db.tenant_tx(TenantCtx(tid_a)) as c:
        c.execute("SELECT 1")
    # same physical connection (pool of 1), no tenant set this time
    with pytest.raises(psycopg.Error):
        with db.pool().connection() as c:
            c.execute("SELECT * FROM users").fetchall()


def test_insert_for_other_tenant_rejected(pool1, two_tenants):
    tid_a, _ = two_tenants["a"]
    tid_b, _ = two_tenants["b"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.tenant_tx(TenantCtx(tid_a)) as c:
            c.execute(
                "INSERT INTO users (tenant_id, role, phone_fp, phone_enc) "
                "VALUES (%s, 'patient', %s, %s)",
                (tid_b, uuid.uuid4().bytes, b"x"),
            )


def test_other_tenant_id_lookup_returns_nothing(pool1, two_tenants):
    tid_a, _ = two_tenants["a"]
    _, uid_b = two_tenants["b"]
    with db.tenant_tx(TenantCtx(tid_a)) as c:
        assert c.execute("SELECT * FROM users WHERE id = %s", (uid_b,)).fetchone() is None
