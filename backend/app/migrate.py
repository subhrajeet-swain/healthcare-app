"""Applies migrations/*.sql in name order, each once, as the owner role."""

from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).parent / "migrations"


def run(owner_url: str, graph_url: str | None = None) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(owner_url, autocommit=True) as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {r[0] for r in c.execute("SELECT name FROM schema_migrations")}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name in done:
                continue
            with c.transaction():
                c.execute(f.read_text(encoding="utf-8"))
                c.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
            applied.append(f.name)
    if graph_url:
        setup_checkpointer(graph_url)
    return applied


def setup_checkpointer(graph_url: str) -> None:
    """LangGraph checkpoint tables, created by hc_graph inside the graph schema. Idempotent."""
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row

    with psycopg.connect(
        graph_url,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options="-c search_path=graph",
    ) as conn:
        PostgresSaver(conn).setup()


if __name__ == "__main__":
    from app.config import settings

    if not (settings.owner_database_url and settings.graph_database_url):
        raise SystemExit("OWNER_DATABASE_URL and GRAPH_DATABASE_URL are required for migrations")
    print(run(settings.owner_database_url, settings.graph_database_url))
