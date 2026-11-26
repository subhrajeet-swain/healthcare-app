"""Family profiles: a patient manages a child (no phone, no login) or invites an adult by phone.

Acting for a member is X-Profile, checked in auth.current_ctx. These routes are the signed-in
patient's own: never with a profile, never for staff."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from app import db, files
from app.audit import audit
from app.auth import Own
from app.brain import factsheet
from app.crypto import cipher_for, normalise_phone
from app.errors import ApiError, not_found
from app.privacy import _delete_user

MAX_PENDING_INVITES = 10


def _own_patient(ctx: Own) -> None:
    # a dependency, so it runs before body validation: staff get 404, never a 422
    if ctx.role != "patient":
        raise not_found()


router = APIRouter(prefix="/api/family", dependencies=[Depends(_own_patient)])


class FamilyIn(BaseModel):
    relation: Literal["child", "parent", "spouse", "other"]
    name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    version: str | None = Field(default=None, max_length=32)  # the consent text, for a child


def _invitee_label(cipher, row) -> str | None:
    """How a member sees the manager asking: their name, else their masked phone."""
    if row["name_enc"]:
        return cipher.decrypt(row["name_enc"])
    if row["phone_enc"]:
        phone = cipher.decrypt(row["phone_enc"])
        return phone[:3] + "******" + phone[-4:]
    return None


@router.post("", status_code=201)
def add(body: FamilyIn, ctx: Own) -> dict:
    name = body.name.strip()
    if not name:
        raise ApiError(422, "invalid_name")
    child = body.relation == "child"
    if child and (body.phone is not None or not body.version):
        raise ApiError(422, "invalid_child")  # a child has no phone and needs the consent text
    if not child:
        try:
            phone = normalise_phone(body.phone or "")
        except ValueError:
            raise ApiError(422, "invalid_phone") from None
    with db.tenant_tx(ctx) as c:
        cipher = cipher_for(c, ctx.tenant_id)
        if child:
            mid = c.execute(
                "INSERT INTO users (tenant_id, role, name_enc) VALUES (%s, 'patient', %s) "
                "RETURNING id",
                (ctx.tenant_id, cipher.encrypt(name)),  # the manager made this user
            ).fetchone()["id"]
            c.execute(
                "INSERT INTO consents (tenant_id, user_id, purpose, version, granted_by) "
                "VALUES (%s, %s, 'core', %s, %s)",
                (ctx.tenant_id, mid, body.version, ctx.user_id),
            )
            audit(c, ctx, "create", "user", mid)
            audit(c, ctx, "consent_grant", "consent", mid)
        else:
            pending = c.execute(
                "SELECT count(*) AS n FROM family_links "
                "WHERE manager_id = %s AND status = 'pending'",
                (ctx.user_id,),
            ).fetchone()["n"]
            if pending >= MAX_PENDING_INVITES:
                raise ApiError(429, "too_many_invites")
            fp = cipher.fingerprint(phone)
            user = c.execute("SELECT id, role FROM users WHERE phone_fp = %s", (fp,)).fetchone()
            if user is None:
                # no name: the manager's typed name is their label, never the person's name
                mid = c.execute(
                    "INSERT INTO users (tenant_id, role, phone_fp, phone_enc) "
                    "VALUES (%s, 'patient', %s, %s) RETURNING id",
                    (ctx.tenant_id, fp, cipher.encrypt(phone)),
                ).fetchone()["id"]
                audit(c, ctx, "create", "user", mid)
            elif user["role"] != "patient":
                raise ApiError(409, "not_a_patient")
            elif user["id"] == ctx.user_id:
                raise ApiError(409, "own_phone")
            else:
                mid = user["id"]
        # a revoked link can be renewed; a live one is a conflict
        link = c.execute(
            "INSERT INTO family_links (tenant_id, manager_id, member_id, relation, status, "
            "accepted_at, label_enc) VALUES (%(t)s, %(me)s, %(m)s, %(r)s, %(st)s, "
            "CASE WHEN %(st)s = 'active' THEN now() END, %(lab)s) "
            "ON CONFLICT (tenant_id, manager_id, member_id) DO UPDATE SET "
            "relation = EXCLUDED.relation, status = EXCLUDED.status, created_at = now(), "
            "accepted_at = EXCLUDED.accepted_at, label_enc = EXCLUDED.label_enc "
            "WHERE family_links.status = 'revoked' RETURNING id, status",
            {"t": ctx.tenant_id, "me": ctx.user_id, "m": mid, "r": body.relation,
             "st": "active" if child else "pending", "lab": cipher.encrypt(name)},
        ).fetchone()
        if link is None:
            raise ApiError(409, "already_linked")
        audit(c, ctx, "create", "family_link", link["id"])
    return {"link_id": str(link["id"]), "member_id": str(mid), "status": link["status"]}


@router.get("")
def list_family(ctx: Own) -> dict:
    """members: whom I manage (pending or active). invites: who manages me, or asks to."""
    with db.tenant_tx(ctx) as c:
        cipher = cipher_for(c, ctx.tenant_id)
        rows = c.execute(
            "SELECT l.id, l.manager_id, l.member_id, l.relation, l.status, l.label_enc, "
            "u.name_enc, u.phone_enc FROM family_links l JOIN users u ON u.id = CASE WHEN "
            "l.manager_id = %s THEN l.member_id ELSE l.manager_id END "
            "WHERE (l.manager_id = %s OR l.member_id = %s) AND l.status <> 'revoked' "
            "ORDER BY l.created_at",
            (ctx.user_id, ctx.user_id, ctx.user_id),
        ).fetchall()
        audit(c, ctx, "list", "family_link", ctx.user_id)
    out: dict = {"members": [], "invites": []}
    for r in rows:
        mine = r["manager_id"] == ctx.user_id
        out["members" if mine else "invites"].append({
            "link_id": str(r["id"]),
            ("member_id" if mine else "manager_id"): str(r["member_id" if mine else "manager_id"]),
            "relation": r["relation"],
            "status": r["status"],
            # the manager sees only their own label: the member's stored name (often typed
            # by lab staff) never reaches someone who only knows their phone number
            "name": (cipher.decrypt(r["label_enc"]) if r["label_enc"] else None) if mine
            else _invitee_label(cipher, r),
        })
    return out


@router.post("/{link_id}/accept")
def accept(link_id: UUID, ctx: Own) -> dict:
    with db.tenant_tx(ctx) as c:
        row = c.execute(
            "UPDATE family_links SET status = 'active', accepted_at = now() "
            "WHERE id = %s AND member_id = %s AND status = 'pending' RETURNING id",
            (link_id, ctx.user_id),
        ).fetchone()
        if row is None:
            raise not_found()
        audit(c, ctx, "accept", "family_link", link_id)
    return {"status": "active"}


@router.delete("/{link_id}", status_code=204)
def revoke(link_id: UUID, ctx: Own) -> Response:
    """Either side ends a link. A manager removing a phoneless child that no one else manages
    deletes the child, as delete_me would: no one could ever reach their reports again."""
    report_ids: list = []
    with db.tenant_tx(ctx) as c:
        row = c.execute(
            "UPDATE family_links SET status = 'revoked' WHERE id = %s "
            "AND %s IN (manager_id, member_id) AND status <> 'revoked' "
            "RETURNING manager_id, member_id",
            (link_id, ctx.user_id),
        ).fetchone()
        if row is None:
            raise not_found()
        audit(c, ctx, "revoke", "family_link", link_id)
        orphan = row["manager_id"] == ctx.user_id and c.execute(
            "SELECT 1 FROM users u WHERE u.id = %s AND u.phone_fp IS NULL AND NOT EXISTS ("
            "SELECT 1 FROM family_links o WHERE o.member_id = u.id AND o.status = 'active')",
            (row["member_id"],),
        ).fetchone()
        if orphan:
            report_ids = _delete_user(c, ctx, row["member_id"])
    # after commit: a failed delete must not leave rows pointing at missing files
    for rid in report_ids:
        files.remove(ctx.tenant_id, rid)
        factsheet.evict(ctx.tenant_id, rid)
    return Response(status_code=204)
