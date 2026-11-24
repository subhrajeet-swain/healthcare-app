import psycopg
import pytest


def test_checkpoint_tables_in_graph_schema_owned_by_hc_graph(db_urls):
    with psycopg.connect(db_urls["owner"]) as c:
        rows = c.execute(
            "SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'graph'"
        ).fetchall()
    tables = dict(rows)
    assert "checkpoints" in tables
    assert set(tables.values()) == {"hc_graph"}


def test_app_role_cannot_read_checkpoints(db_urls):
    with psycopg.connect(db_urls["app"]) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT * FROM graph.checkpoints")
