import psycopg

from app.tenancy import TenantCtx


def audit(
    conn: psycopg.Connection, ctx: TenantCtx, action: str, entity: str, entity_id: str
) -> None:
    """Append one audit row in the caller's transaction. The actor is who signed in, also
    when acting for a family member."""
    conn.execute(
        "INSERT INTO audit_log (tenant_id, actor_user_id, action, entity, entity_id) "
        "VALUES (%s, %s, %s, %s, %s)",
        (ctx.tenant_id, ctx.actor_id or ctx.user_id, action, entity, str(entity_id)),
    )
