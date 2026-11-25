import psycopg

from app.tenancy import TenantCtx


def audit(
    conn: psycopg.Connection, ctx: TenantCtx, action: str, entity: str, entity_id: str
) -> None:
    """Append one audit row in the caller's transaction."""
    conn.execute(
        "INSERT INTO audit_log (tenant_id, actor_user_id, action, entity, entity_id) "
        "VALUES (%s, %s, %s, %s, %s)",
        (ctx.tenant_id, ctx.user_id, action, entity, str(entity_id)),
    )
