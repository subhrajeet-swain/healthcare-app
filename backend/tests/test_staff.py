import uuid

import pytest
from fastapi.testclient import TestClient

from app import crypto, db
from app.config import settings
from app.main import app
from tests.conftest import CONSENT, pdf_bytes

STAFF_PHONE = "+919100000101"
PATIENT_PHONE = "9876543210"


def make_user(tid, phone, role, name=None):
    with db.owner_tx(settings.owner_database_url, tid) as c:
        cipher = crypto.cipher_for(c, tid)
        e164 = crypto.normalise_phone(phone)
        return c.execute(
            "INSERT INTO users (tenant_id, role, phone_fp, phone_enc, name_enc) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (tid, role, cipher.fingerprint(e164), cipher.encrypt(e164),
             cipher.encrypt(name) if name else None),
        ).fetchone()["id"]


@pytest.fixture
def staff(client, lab, login):
    slug, tid = lab
    make_user(tid, STAFF_PHONE, "lab_staff")
    assert login(slug, STAFF_PHONE).status_code == 200
    return slug, tid


def _order(client, phone=PATIENT_PHONE, name="Asha Rao"):
    return client.post("/api/staff/orders", json={"phone": phone, "name": name})


def _file(client, rid, data=None):
    data = data or pdf_bytes()
    return client.post(f"/api/staff/reports/{rid}/file",
                       files={"file": ("r.pdf", data, "application/pdf")})


def _owner(tid):
    return db.owner_tx(settings.owner_database_url, tid)


def test_patient_gets_404_on_staff_routes(client, patient):
    rid = uuid.uuid4()
    for method, url in [("POST", "/api/staff/orders"), ("GET", "/api/staff/reports"),
                        ("POST", f"/api/staff/reports/{rid}/status"),
                        ("POST", f"/api/staff/reports/{rid}/file")]:
        r = client.request(method, url, json={"phone": PATIENT_PHONE, "status": "in_lab"})
        assert r.status_code == 404 and r.json() == {"error": "not_found"}, url


def test_order_for_new_phone_creates_patient(client, staff):
    _, tid = staff
    r = _order(client)
    assert r.status_code == 201
    rid = r.json()["id"]
    with _owner(tid) as c:
        rep = c.execute("SELECT * FROM reports WHERE id = %s", (rid,)).fetchone()
        user = c.execute("SELECT * FROM users WHERE id = %s", (rep["user_id"],)).fetchone()
        cipher = crypto.cipher_for(c, tid)
    assert (rep["source"], rep["status"]) == ("lab", "sample_collected")
    assert user["role"] == "patient"
    assert cipher.decrypt(user["phone_enc"]) == "+919876543210"
    assert cipher.decrypt(user["name_enc"]) == "Asha Rao"


def test_order_for_existing_phone_reuses_patient(client, staff):
    _, tid = staff
    _order(client)
    _order(client, phone="+91 98765 43210", name=None)
    with _owner(tid) as c:
        n = c.execute("SELECT count(*) AS n FROM users WHERE role = 'patient'").fetchone()["n"]
        m = c.execute("SELECT count(DISTINCT user_id) AS n FROM reports").fetchone()["n"]
    assert (n, m) == (1, 1)


def test_order_names_a_nameless_patient_but_never_renames(client, staff):
    _, tid = staff
    uid = make_user(tid, PATIENT_PHONE, "patient")  # e.g. created by a family invite
    _order(client)
    _order(client, name="Someone Else")
    with _owner(tid) as c:
        cipher = crypto.cipher_for(c, tid)
        row = c.execute("SELECT name_enc FROM users WHERE id = %s", (uid,)).fetchone()
    assert cipher.decrypt(row["name_enc"]) == "Asha Rao"


def test_order_for_staff_phone_is_409(client, staff):
    r = _order(client, phone=STAFF_PHONE)
    assert r.status_code == 409 and r.json() == {"error": "not_a_patient"}


def test_order_bad_phone_is_422(client, staff):
    assert _order(client, phone="12345").json() == {"error": "invalid_phone"}


def test_status_only_moves_forward(client, staff):
    rid = _order(client).json()["id"]
    url = f"/api/staff/reports/{rid}/status"
    assert client.post(url, json={"status": "in_lab"}).status_code == 200
    r = client.post(url, json={"status": "in_lab"})
    assert r.status_code == 409 and r.json() == {"error": "bad_transition"}
    assert client.post(url, json={"status": "ready"}).status_code == 422


def test_staff_upload_queues_pipeline_and_patient_sees_it(client, staff, login):
    slug, tid = staff
    rid = _order(client).json()["id"]
    client.post(f"/api/staff/reports/{rid}/status", json={"status": "in_lab"})
    assert _file(client, rid).status_code == 200
    assert _file(client, rid).status_code == 409  # already received
    listed = client.get("/api/staff/reports").json()
    row = next(x for x in listed if x["id"] == rid)
    assert row["status"] == "received" and row["phone_masked"] == "+91******3210"
    with _owner(tid) as c:
        assert c.execute("SELECT count(*) AS n FROM jobs WHERE payload->>'report_id' = %s",
                         (rid,)).fetchone()["n"] == 1
    with TestClient(app) as pc:
        login(slug, PATIENT_PHONE, c=pc)
        pc.post("/api/consents", json=CONSENT)
        mine = pc.get("/api/reports").json()
        assert [x["id"] for x in mine] == [rid] and mine[0]["source"] == "lab"
        d = pc.get(f"/api/reports/{rid}").json()
        assert [s["status"] for s in d["steps"]] == ["sample_collected", "in_lab", "received"]


def test_staff_upload_rejects_bad_file(client, staff):
    rid = _order(client).json()["id"]
    assert _file(client, rid, b"<html>").status_code == 415


def test_staff_cannot_touch_other_tenant_report(client, staff):
    slug_b = f"lab-{uuid.uuid4().hex[:8]}"
    tid_b = crypto.provision_tenant(slug_b, slug_b)
    uid = make_user(tid_b, PATIENT_PHONE, "patient")
    with _owner(tid_b) as c:
        rid = c.execute(
            "INSERT INTO reports (tenant_id, user_id, uploaded_by, source, status) "
            "VALUES (%s, %s, %s, 'lab', 'sample_collected') RETURNING id", (tid_b, uid, uid),
        ).fetchone()["id"]
    r = client.post(f"/api/staff/reports/{rid}/status", json={"status": "in_lab"})
    assert r.status_code == 404
    assert _file(client, rid).status_code == 404
