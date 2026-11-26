import uuid

import pytest
from fastapi.testclient import TestClient

from app import crypto, db, seed
from app.config import settings
from app.main import app
from app.tenancy import TenantCtx

SHARED = "+919000000001"


@pytest.fixture(scope="module")
def seeded(db_urls):
    first = seed.run()
    assert seed.run() == first  # idempotent
    return first


def _users(tid):
    with db.owner_tx(settings.owner_database_url, tid) as c:
        cipher = crypto.cipher_for(c, tid)
        rows = c.execute("SELECT id, name_enc, phone_fp FROM users").fetchall()
        return cipher, rows


def test_shared_phone_two_tenants_two_users(seeded):
    found = []
    for lab in ("lab-alpha", "lab-beta"):
        cipher, rows = _users(seeded[lab])
        matches = [r["id"] for r in rows if bytes(r["phone_fp"]) == cipher.fingerprint(SHARED)]
        assert len(matches) == 1
        found.append(matches[0])
    assert found[0] != found[1]
    assert found == [seeded["lab-alpha:shared"], seeded["lab-beta:shared"]]


def test_seed_gives_lab_alpha_its_dev_whatsapp_number(seeded):
    with db.owner_tx(settings.owner_database_url) as c:
        rows = {
            r["slug"]: (r["wa_phone_number_id"], r["wa_display_phone"])
            for r in c.execute("SELECT slug, wa_phone_number_id, wa_display_phone FROM tenants")
        }
    assert rows["lab-alpha"] == ("dev-alpha", "+15550000001")
    assert rows["lab-beta"] == (None, None)


def test_canary_never_crosses(seeded):
    for lab, own, other in [
        ("lab-alpha", "CANARY-ALPHA", "CANARY-BETA"),
        ("lab-beta", "CANARY-BETA", "CANARY-ALPHA"),
    ]:
        cipher, rows = _users(seeded[lab])
        names = [cipher.decrypt(r["name_enc"]) for r in rows if r["name_enc"]]
        assert any(own in n for n in names)
        assert not any(other in n for n in names)


def test_login_as_alpha_cannot_reach_beta_user(seeded, client, login):
    assert login("lab-alpha", SHARED).status_code == 200
    me = client.get("/api/me").json()
    assert me["id"] == str(seeded["lab-alpha:shared"])
    assert me["name"].startswith("CANARY-ALPHA")


def test_every_api_route_rejects_cross_tenant_cookie(seeded, client, login):
    login("lab-alpha", SHARED)
    token = client.cookies.get("hc_session").split(".", 1)[1]
    forged = f"{seeded['lab-beta']}.{token}"
    checked = 0
    # openapi paths: public and flat (app.routes nests included routers in this FastAPI)
    for path, ops in app.openapi()["paths"].items():
        # the two public doors take no cookie: login by slug, and a share link by slug + token
        public = ("/api/auth/{slug}", "/api/share/{slug}")
        if not path.startswith("/api/") or path.startswith(public):
            continue
        url = path.replace("{purpose}", "core").replace("{report_id}", str(uuid.uuid4()))
        for method in (m.upper() for m in ops):
            with TestClient(app) as c:
                c.cookies.set("hc_session", forged)
                r = c.request(method, url, json={"purpose": "core", "version": "v1"})
            assert r.status_code == 401, (method, url, r.status_code)
            checked += 1
    assert checked >= 6


def test_tenant_ctx_for_alpha_never_lists_beta_rows(seeded, db_urls):
    db.init_pool(db_urls["app"])
    try:
        with db.tenant_tx(TenantCtx(seeded["lab-alpha"])) as c:
            ids = {r["id"] for r in c.execute("SELECT id FROM users")}
    finally:
        db.close_pool()
    assert seeded["lab-beta:shared"] not in ids
    assert seeded["lab-alpha:shared"] in ids


def _beta_report_ids(seeded):
    with db.owner_tx(settings.owner_database_url, seeded["lab-beta"]) as c:
        return [r["id"] for r in c.execute("SELECT id FROM reports ORDER BY created_at")]


@pytest.mark.parametrize("phone", [SHARED, "+919100000103"])  # alpha patient, alpha staff
def test_alpha_session_gets_404_on_every_beta_report(seeded, phone, login):
    from tests.conftest import pdf_bytes

    beta_ids = _beta_report_ids(seeded)
    assert beta_ids, "seed must give beta reports"
    checked = 0
    with TestClient(app) as c:
        assert login("lab-alpha", phone, c=c).status_code == 200
        c.post("/api/consents", json={"purpose": "core", "version": "v1"})
        for path, ops in app.openapi()["paths"].items():
            if "{report_id}" not in path:
                continue
            for rid in beta_ids:
                url = path.replace("{report_id}", str(rid))
                for method in (m.upper() for m in ops):
                    kw = {"json": {"question": "what is my hemoglobin", "language": "en",
                                   "status": "in_lab"}}
                    if path.endswith("/file") and method == "POST":
                        kw = {"files": {"file": ("r.pdf", pdf_bytes(), "application/pdf")}}
                    r = c.request(method, url, **kw)
                    assert r.status_code == 404, (phone, method, url, r.status_code)
                    assert "CANARY-BETA" not in r.text and "12.7" not in r.text
                    checked += 1
    assert checked >= 2 * 7


@pytest.fixture(scope="module")
def alpha_phase2_rows(seeded):
    """One row in each phase 2 table, in lab alpha."""
    tid = seeded["lab-alpha"]
    with db.owner_tx(settings.owner_database_url, tid) as c:
        uid = c.execute("SELECT id FROM users WHERE role = 'patient' LIMIT 1").fetchone()["id"]
        other = c.execute(
            "SELECT id FROM users WHERE role = 'patient' AND id <> %s LIMIT 1", (uid,)
        ).fetchone()["id"]
        rid = c.execute(
            "SELECT id FROM reports WHERE user_id = %s LIMIT 1", (uid,)
        ).fetchone()["id"]
        c.execute(
            "INSERT INTO trends (tenant_id, user_id, test_id, direction, toward, first_value, "
            "last_value, unit_c, points, last_report_id) "
            "VALUES (%s, %s, 'hba1c.hba1c', 'rising', 'out_of_range', 6.1, 7.0, '%%', 3, %s)",
            (tid, uid, rid),
        )
        c.execute(
            "INSERT INTO review_items (tenant_id, kind, reason, user_id, report_id, due_at) "
            "VALUES (%s, 'report', 'red', %s, %s, now())", (tid, uid, rid),
        )
        c.execute(
            "INSERT INTO family_links (tenant_id, manager_id, member_id, relation, status) "
            "VALUES (%s, %s, %s, 'spouse', 'pending')", (tid, uid, other),
        )
        c.execute(
            "INSERT INTO share_links (tenant_id, user_id, created_by, token_hash, report_ids, "
            "expires_at) VALUES (%s, %s, %s, %s, %s, now() + interval '1 day')",
            (tid, uid, uid, uuid.uuid4().bytes, [rid]),
        )


@pytest.mark.parametrize("table", ["trends", "review_items", "family_links", "share_links"])
def test_phase2_rows_never_cross(seeded, alpha_phase2_rows, table):
    for lab, expect_rows in (("lab-alpha", True), ("lab-beta", False)):
        with db.owner_tx(settings.owner_database_url, seeded[lab]) as c:
            n = c.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
        assert (n > 0) == expect_rows, (lab, table)


def test_seeded_results_carry_user_and_observed_on(seeded):
    with db.owner_tx(settings.owner_database_url, seeded["lab-alpha"]) as c:
        rows = c.execute(
            "SELECT r.user_id, r.observed_on, rp.user_id AS owner, rp.collected_on "
            "FROM results r JOIN reports rp ON rp.id = r.report_id"
        ).fetchall()
    assert rows and all(
        r["user_id"] == r["owner"] and r["observed_on"] == r["collected_on"] for r in rows
    )
