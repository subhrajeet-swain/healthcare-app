import psycopg
import pytest

from app import migrate


def test_migrate_is_idempotent(db_urls):
    assert migrate.run(db_urls["owner"]) == []


def test_every_tenant_table_has_forced_rls_and_policy(db_urls):
    with psycopg.connect(db_urls["owner"]) as c:
        rows = c.execute(
            """
            SELECT cl.relname, cl.relrowsecurity, cl.relforcerowsecurity,
                   (SELECT count(*) FROM pg_policies p
                     WHERE p.schemaname = 'public' AND p.tablename = cl.relname) AS policies
            FROM pg_class cl
            JOIN pg_namespace n ON n.oid = cl.relnamespace AND n.nspname = 'public'
            JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attname = 'tenant_id'
            WHERE cl.relkind IN ('r', 'p')
            """
        ).fetchall()
    assert len(rows) >= 8
    bad = [r[0] for r in rows if not (r[1] and r[2] and r[3] >= 1)]
    assert bad == []


def test_app_role_cannot_bypass_rls(db_urls):
    with psycopg.connect(db_urls["owner"]) as c:
        row = c.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname='hc_app'").fetchone()
    assert row[0] is False


@pytest.mark.parametrize("sql", ["UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log"])
def test_audit_log_is_append_only_for_app(db_urls, sql):
    with psycopg.connect(db_urls["app"]) as c:
        # a tenant must be set, otherwise the RLS policy errors at plan time first
        c.execute("SELECT set_config('app.tenant_id', gen_random_uuid()::text, false)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(sql)


def test_app_role_has_no_access_to_graph_schema(db_urls):
    with psycopg.connect(db_urls["app"]) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("CREATE TABLE graph.x()")
