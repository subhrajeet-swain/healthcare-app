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
        if not path.startswith("/api/") or path.startswith("/api/auth/{slug}"):
            continue
        url = path.replace("{purpose}", "core")
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
