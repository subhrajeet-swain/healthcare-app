import uuid
from datetime import date

import psycopg
import pytest

from app import db, reports
from app.brain.flags import flag_report
from app.brain.models import ExtractedReport
from app.brain.pipeline import template_result
from app.config import settings
from app.tenancy import TenantCtx


def _patient(tid):
    with db.owner_tx(settings.owner_database_url, tid) as c:
        return c.execute(
            "INSERT INTO users (tenant_id, role, phone_fp, phone_enc) "
            "VALUES (%s, 'patient', %s, 'x') RETURNING id",
            (tid, uuid.uuid4().bytes),
        ).fetchone()["id"]


def _report(tid, uid):
    with db.owner_tx(settings.owner_database_url, tid) as c:
        return c.execute(
            "INSERT INTO reports (tenant_id, user_id, uploaded_by, source, status) "
            "VALUES (%s, %s, %s, 'patient', 'received') RETURNING id",
            (tid, uid, uid),
        ).fetchone()["id"]


@pytest.fixture
def two_labs(lab):
    from app import crypto

    a = lab[1]
    b = crypto.provision_tenant(f"lab-{uuid.uuid4().hex[:8]}", "b")
    for tid in (a, b):
        with db.owner_tx(settings.owner_database_url, tid) as c:
            c.execute("INSERT INTO jobs (tenant_id, kind) VALUES (%s, 'test')", (tid,))
    return a, b


def test_worker_sees_all_jobs_but_no_reports_without_tenant(two_labs):
    a, b = two_labs
    with psycopg.connect(settings.worker_database_url) as c:
        tenants = {r[0] for r in c.execute("SELECT tenant_id FROM jobs")}
        assert {a, b} <= tenants
        with pytest.raises(psycopg.errors.UndefinedObject):
            c.execute("SELECT count(*) FROM reports")


def test_app_role_sees_only_own_jobs(two_labs):
    a, b = two_labs
    with psycopg.connect(settings.database_url) as c:
        c.execute("SELECT set_config('app.tenant_id', %s, false)", (str(a),))
        tenants = {r[0] for r in c.execute("SELECT tenant_id FROM jobs")}
    assert tenants == {a}


def test_worker_is_not_bypassrls(db_urls):
    with psycopg.connect(db_urls["owner"]) as c:
        row = c.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname='hc_worker'").fetchone()
    assert row[0] is False


def test_report_step_insert_notifies(lab):
    tid = lab[1]
    rid = _report(tid, _patient(tid))
    with psycopg.connect(settings.database_url, autocommit=True) as listener:
        listener.execute("LISTEN report_status")
        with db.owner_tx(settings.owner_database_url, tid) as c:
            c.execute(
                "INSERT INTO report_steps (tenant_id, report_id, status) "
                "VALUES (%s, %s, 'extracting')",
                (tid, rid),
            )
        got = [n.payload for n in listener.notifies(timeout=3, stop_after=1)]
    assert got == [f"{rid}:extracting"]


def test_new_tables_usable_by_app_under_tenant(lab):
    tid = lab[1]
    uid = _patient(tid)
    db.init_pool(settings.database_url, max_size=1)
    try:
        with db.tenant_tx(TenantCtx(tid)) as c:
            rid = c.execute(
                "INSERT INTO reports (tenant_id, user_id, uploaded_by, source, status) "
                "VALUES (%s, %s, %s, 'patient', 'received') RETURNING id",
                (tid, uid, uid),
            ).fetchone()["id"]
            c.execute(
                "INSERT INTO results (tenant_id, report_id, user_id, observed_on, test_id, "
                "test_name, value, unit, flag, triage) "
                "VALUES (%s, %s, %s, '2026-11-01', 'cbc.hemoglobin', 'Hb', 11.2, 'g/dL', "
                "'low', 'amber')",
                (tid, rid, uid),
            )
            c.execute(
                "INSERT INTO explanations (tenant_id, report_id, language, source, statements) "
                "VALUES (%s, %s, 'en', 'model', '[]')",
                (tid, rid),
            )
            c.execute(
                "INSERT INTO report_steps (tenant_id, report_id, status) "
                "VALUES (%s, %s, 'received')",
                (tid, rid),
            )
            c.execute(
                "INSERT INTO chat_messages (tenant_id, report_id, user_id, role, text_enc, tier) "
                "VALUES (%s, %s, %s, 'user', 'x', 'tier0')",
                (tid, rid, uid),
            )
            c.execute("DELETE FROM reports WHERE id = %s", (rid,))
            left = c.execute(
                "SELECT (SELECT count(*) FROM results) + (SELECT count(*) FROM explanations) "
                "+ (SELECT count(*) FROM report_steps) + (SELECT count(*) FROM chat_messages) AS n"
            ).fetchone()["n"]
        assert left == 0
    finally:
        db.close_pool()


def test_report_status_is_constrained(lab):
    tid = lab[1]
    uid = _patient(tid)
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.owner_tx(settings.owner_database_url, tid) as c:
            c.execute(
                "INSERT INTO reports (tenant_id, user_id, uploaded_by, source, status) "
                "VALUES (%s, %s, %s, 'patient', 'done')",
                (tid, uid, uid),
            )


@pytest.mark.parametrize("collected", [date(2026, 11, 2), None])
def test_store_result_sets_user_and_observed_on(lab, collected):
    tid = lab[1]
    uid = _patient(tid)
    row = {"test_id": "cbc.hemoglobin", "test_name": "Hemoglobin", "value": 11.2, "unit": "g/dL",
           "ref_low": 13.0, "ref_high": 17.0, "printed_flag": "L"}
    report, _ = flag_report(ExtractedReport(collected_on=collected, results=[row]))
    with db.owner_tx(settings.owner_database_url, tid) as c:
        rid = reports.create_report(c, TenantCtx(tid, uid, "patient"), uid, "patient", "received")
        reports.store_result(c, tid, rid, template_result(report))
        created = c.execute("SELECT created_at::date AS d FROM reports WHERE id = %s", (rid,))
        created = created.fetchone()["d"]
        rows = c.execute(
            "SELECT user_id, observed_on, value_c FROM results WHERE report_id = %s", (rid,)
        ).fetchall()
    assert rows == [{"user_id": uid, "observed_on": collected or created, "value_c": 11.2}]
