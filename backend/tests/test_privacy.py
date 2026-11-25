from app import db

CONSENT = {"purpose": "core", "version": "2026-11-v1"}


def _audit_actions(db_urls, tid):
    with db.owner_tx(db_urls["owner"], tid) as c:
        return [r["action"] for r in c.execute("SELECT action FROM audit_log ORDER BY id")]


def test_me_requires_login(client):
    r = client.get("/api/me")
    assert r.status_code == 401 and r.json() == {"error": "unauthenticated"}


def test_me_masks_phone_and_audits_read(client, lab, login, db_urls):
    slug, tid = lab
    login(slug, "9876543210")
    me = client.get("/api/me").json()
    assert me["phone_masked"] == "+91******3210"
    assert me["role"] == "patient" and me["name"] is None
    assert me["consent"] == {"core": False}
    assert "read" in _audit_actions(db_urls, tid)


def test_consent_grant_and_withdraw_reflected_in_me(client, lab, login):
    login(lab[0])
    assert client.post("/api/consents", json=CONSENT).status_code == 201
    assert client.get("/api/me").json()["consent"] == {"core": True}
    assert client.delete("/api/consents/core").status_code == 204
    assert client.get("/api/me").json()["consent"] == {"core": False}


def test_unknown_consent_purpose_422(client, lab, login):
    login(lab[0])
    r = client.post("/api/consents", json={"purpose": "marketing", "version": "v1"})
    assert r.status_code == 422


def test_export_contains_decrypted_data_and_audits(client, lab, login, db_urls):
    slug, tid = lab
    login(slug, "9876543210")
    client.post("/api/consents", json=CONSENT)
    r = client.get("/api/me/export")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["user"]["phone"] == "+919876543210"
    assert [c["purpose"] for c in data["consents"]] == ["core"]
    assert "export" in _audit_actions(db_urls, tid)


def test_delete_removes_rows_and_session(client, lab, login, db_urls):
    slug, tid = lab
    login(slug)
    uid = client.get("/api/me").json()["id"]
    client.post("/api/consents", json=CONSENT)
    assert client.delete("/api/me").status_code == 204
    with db.owner_tx(db_urls["owner"], tid) as c:
        for table, col in [("users", "id"), ("sessions", "user_id"), ("consents", "user_id")]:
            n = c.execute(f"SELECT count(*) AS n FROM {table} WHERE {col} = %s", (uid,))
            assert n.fetchone()["n"] == 0, table
        audit = c.execute(
            "SELECT 1 FROM audit_log WHERE action = 'delete' AND entity_id = %s", (uid,)
        ).fetchone()
    assert audit is not None


def test_relogin_after_delete_is_fresh_account(client, lab, login):
    slug = lab[0]
    login(slug)
    old_id = client.get("/api/me").json()["id"]
    client.post("/api/consents", json=CONSENT)
    client.delete("/api/me")
    login(slug)
    me = client.get("/api/me").json()
    assert me["id"] != old_id
    assert me["consent"] == {"core": False}


def test_second_delete_with_old_cookie_is_401(client, lab, login):
    login(lab[0])
    old = client.cookies.get("hc_session")
    assert client.delete("/api/me").status_code == 204
    client.cookies.set("hc_session", old)
    r = client.delete("/api/me")
    assert r.status_code == 401 and r.json() == {"error": "unauthenticated"}
