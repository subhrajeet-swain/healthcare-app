import uuid

import psycopg
import pytest

from app import db, migrate
from app.config import settings


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


PHASE2 = ["trends", "review_items", "family_links", "share_links"]
PHASE3 = ["channel_links", "link_codes", "inbound_messages"]


def _assert_forced_rls(db_urls, tables):
    with psycopg.connect(db_urls["owner"]) as c:
        for t in tables:
            row = c.execute(
                "SELECT relrowsecurity, relforcerowsecurity, "
                "(SELECT count(*) FROM pg_policies WHERE schemaname = 'public' AND tablename = %s) "
                "FROM pg_class WHERE relname = %s AND relkind = 'r'",
                (t, t),
            ).fetchone()
            assert row is not None and row[0] and row[1] and row[2] >= 1, t


def test_phase2_tables_have_forced_rls(db_urls):
    _assert_forced_rls(db_urls, PHASE2)


def test_phase3_tables_have_forced_rls(db_urls):
    _assert_forced_rls(db_urls, PHASE3)


def _user(c, tid, role="patient", fp=True):
    return c.execute(
        "INSERT INTO users (tenant_id, role, phone_fp, phone_enc) VALUES (%s, %s, %s, %s) "
        "RETURNING id",
        (tid, role, uuid.uuid4().bytes if fp else None, b"x" if fp else None),
    ).fetchone()["id"]


def _report(c, tid, uid):
    return c.execute(
        "INSERT INTO reports (tenant_id, user_id, uploaded_by, source, status) "
        "VALUES (%s, %s, %s, 'patient', 'received') RETURNING id",
        (tid, uid, uid),
    ).fetchone()["id"]


def _review(c, tid, uid, rid, status="pending", kind="report", **ids):
    return c.execute(
        "INSERT INTO review_items (tenant_id, kind, reason, user_id, report_id, status, "
        "trend_id, chat_message_id, due_at) "
        "VALUES (%s, %s, 'red', %s, %s, %s, %s, %s, now()) RETURNING id",
        (tid, kind, uid, rid, status, ids.get("trend_id"), ids.get("chat_message_id")),
    ).fetchone()["id"]


def test_one_pending_review_per_report(lab):
    tid = lab[1]
    with db.owner_tx(settings.owner_database_url, tid) as c:
        uid = _user(c, tid)
        rid = _report(c, tid, uid)
        first = _review(c, tid, uid, rid)
    with pytest.raises(psycopg.errors.UniqueViolation) as e:
        with db.owner_tx(settings.owner_database_url, tid) as c:
            _review(c, tid, uid, rid)
    assert e.value.diag.constraint_name == "review_one_pending_report"
    with db.owner_tx(settings.owner_database_url, tid) as c:  # decided, so a new one may open
        c.execute("UPDATE review_items SET status = 'approved' WHERE id = %s", (first,))
        _review(c, tid, uid, rid)


def test_review_status_is_constrained(lab):
    tid = lab[1]
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.owner_tx(settings.owner_database_url, tid) as c:
            uid = _user(c, tid)
            _review(c, tid, uid, _report(c, tid, uid), status="done")


def test_staff_must_have_phone(lab):
    tid = lab[1]
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.owner_tx(settings.owner_database_url, tid) as c:
            _user(c, tid, role="doctor", fp=False)
    with db.owner_tx(settings.owner_database_url, tid) as c:  # a dependant has no phone
        _user(c, tid, role="patient", fp=False)


def _link(c, tid, manager, member, relation="child", status="active"):
    c.execute(
        "INSERT INTO family_links (tenant_id, manager_id, member_id, relation, status) "
        "VALUES (%s, %s, %s, %s, %s)",
        (tid, manager, member, relation, status),
    )


@pytest.mark.parametrize("relation, status", [("sibling", "active"), ("child", "nope")])
def test_family_link_values_are_constrained(lab, relation, status):
    tid = lab[1]
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.owner_tx(settings.owner_database_url, tid) as c:
            _link(c, tid, _user(c, tid), _user(c, tid), relation, status)


def test_family_link_to_self_is_rejected(lab):
    tid = lab[1]
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.owner_tx(settings.owner_database_url, tid) as c:
            a = _user(c, tid)
            _link(c, tid, a, a)


def test_deleting_a_user_removes_phase2_rows(lab):
    tid = lab[1]
    with db.owner_tx(settings.owner_database_url, tid) as c:
        uid, other = _user(c, tid), _user(c, tid)
        rid = _report(c, tid, uid)
        msg = c.execute(
            "INSERT INTO chat_messages (tenant_id, report_id, user_id, role, text_enc, tier) "
            "VALUES (%s, %s, %s, 'user', 'x', 'tier0') RETURNING id", (tid, rid, uid)
        ).fetchone()["id"]
        trend = c.execute(
            "INSERT INTO trends (tenant_id, user_id, test_id, direction, toward, first_value, "
            "last_value, unit_c, points, last_report_id) "
            "VALUES (%s, %s, 'hba1c.hba1c', 'rising', 'out_of_range', 6.1, 7.0, '%%', 3, %s) "
            "RETURNING id", (tid, uid, rid)
        ).fetchone()["id"]
        _review(c, tid, uid, rid)
        _review(c, tid, uid, None, kind="trend", trend_id=trend)
        _review(c, tid, uid, rid, kind="chat", chat_message_id=msg)
        _link(c, tid, other, uid)
        c.execute(
            "INSERT INTO share_links (tenant_id, user_id, created_by, token_hash, report_ids, "
            "expires_at) VALUES (%s, %s, %s, %s, %s, now() + interval '1 day')",
            (tid, uid, uid, uuid.uuid4().bytes, [rid]),
        )
        c.execute("DELETE FROM users WHERE id = %s", (uid,))
        left = [c.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in PHASE2]
    assert left == [0, 0, 0, 0]


def test_results_need_user_and_observed_on(lab):
    tid = lab[1]
    with pytest.raises(psycopg.errors.NotNullViolation):
        with db.owner_tx(settings.owner_database_url, tid) as c:
            uid = _user(c, tid)
            c.execute(
                "INSERT INTO results (tenant_id, report_id, test_id, test_name, value, unit, "
                "flag, triage) VALUES (%s, %s, 'x', 'X', 1, 'u', 'normal', 'green')",
                (tid, _report(c, tid, uid)),
            )


def test_report_source_whatsapp_allowed(lab):
    tid = lab[1]
    with db.owner_tx(settings.owner_database_url, tid) as c:
        uid = _user(c, tid)
        c.execute(
            "INSERT INTO reports (tenant_id, user_id, uploaded_by, source, status) "
            "VALUES (%s, %s, %s, 'whatsapp', 'received')", (tid, uid, uid))
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.owner_tx(settings.owner_database_url, tid) as c:
            uid = _user(c, tid)
            c.execute(
                "INSERT INTO reports (tenant_id, user_id, uploaded_by, source, status) "
                "VALUES (%s, %s, %s, 'sms', 'received')", (tid, uid, uid))


def test_chat_channel_defaults_web(lab):
    tid = lab[1]
    insert = (
        "INSERT INTO chat_messages (tenant_id, report_id, user_id, role, text_enc, tier{col}) "
        "VALUES (%s, %s, %s, 'user', 'x', 'tier0'{val}) RETURNING channel"
    )
    with db.owner_tx(settings.owner_database_url, tid) as c:
        uid = _user(c, tid)
        args = (tid, _report(c, tid, uid), uid)
        assert c.execute(insert.format(col="", val=""), args).fetchone()["channel"] == "web"
        wa = insert.format(col=", channel", val=", 'whatsapp'")
        assert c.execute(wa, args).fetchone()["channel"] == "whatsapp"
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.owner_tx(settings.owner_database_url, tid) as c:
            uid = _user(c, tid)
            args = (tid, _report(c, tid, uid), uid)
            c.execute(insert.format(col=", channel", val=", 'sms'"), args)


def _link_row(c, tid, uid, channel, fp):
    c.execute(
        "INSERT INTO channel_links (tenant_id, user_id, channel, address_fp, address_enc) "
        "VALUES (%s, %s, %s, %s, %s)",
        (tid, uid, channel, fp, b"x"),
    )


def test_channel_unique_keys(lab):
    tid = lab[1]
    with db.owner_tx(settings.owner_database_url, tid) as c:
        uid, other = _user(c, tid), _user(c, tid)
        _link_row(c, tid, uid, "whatsapp", b"a")
        _link_row(c, tid, uid, "telegram", b"a")  # the same address on two channels is fine
    for user, fp in ((uid, b"b"), (other, b"a")):  # a second link; a taken address
        with pytest.raises(psycopg.errors.UniqueViolation):
            with db.owner_tx(settings.owner_database_url, tid) as c:
                _link_row(c, tid, user, "whatsapp", fp)
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.owner_tx(settings.owner_database_url, tid) as c:
            _link_row(c, tid, other, "sms", b"c")


def test_tenant_phone_and_telegram_values(lab):
    tid = lab[1]
    with db.owner_tx(settings.owner_database_url, tid) as c:
        assert c.execute("SELECT phone FROM tenants WHERE id = %s", (tid,)).fetchone()[
            "phone"
        ] is None
        uid = _user(c, tid)
        c.execute(
            "INSERT INTO reports (tenant_id, user_id, uploaded_by, source, status) "
            "VALUES (%s, %s, %s, 'telegram', 'received')",
            (tid, uid, uid),
        )
        row = c.execute(
            "SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint "
            "WHERE conname = 'chat_messages_channel_check'"
        ).fetchone()
        assert "telegram" in row["d"]
