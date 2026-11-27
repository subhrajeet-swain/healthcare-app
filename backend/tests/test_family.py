import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app import db, worker
from app.config import settings
from tests.conftest import CONSENT, pdf_bytes
from tests.test_staff import make_user
from tests.test_worker import _models

MANAGER = "9876543210"
ADULT = "9811111111"
PDF = {"file": ("r.pdf", pdf_bytes(), "application/pdf")}
CHILD = {"relation": "child", "name": "Mira", "version": CONSENT["version"]}


def _owner(tid):
    return db.owner_tx(settings.owner_database_url, tid)


def _as(member_id):
    return {"X-Profile": str(member_id)}


def _add_child(client, name="Mira"):
    r = client.post("/api/family", json={**CHILD, "name": name})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def manager(patient):
    return patient  # (slug, tid, user_id), signed in on `client` with consent


@pytest.fixture
def adult(client, manager, login):
    """A second signed-in patient on their own client; yields (client, user_id)."""
    with TestClient(client.app) as ac:
        assert login(manager[0], ADULT, c=ac).status_code == 200
        yield ac, uuid.UUID(ac.get("/api/me").json()["id"])


def _invite(client, phone=ADULT, relation="parent"):
    return client.post("/api/family", json={"relation": relation, "name": "Papa", "phone": phone})


def test_child_profile_usable_at_once(client, manager):
    child = _add_child(client)
    assert child["status"] == "active"
    cid = child["member_id"]
    me = client.get("/api/me", headers=_as(cid)).json()
    assert me["id"] == cid and me["name"] == "Mira"
    assert me["phone_masked"] is None and me["consent"] == {
        "core": True, "whatsapp": False, "telegram": False}
    # the manager uploads for the child: the report is the child's, uploaded by the manager
    r = client.post("/api/reports", files=PDF, headers=_as(cid))
    assert r.status_code == 201
    mine = client.get("/api/reports", headers=_as(cid)).json()
    assert [x["id"] for x in mine] == [r.json()["id"]]
    assert client.get("/api/reports").json() == []  # not in the manager's own list
    with _owner(manager[1]) as c:
        rep = c.execute("SELECT user_id, uploaded_by FROM reports WHERE id = %s",
                        (r.json()["id"],)).fetchone()
        consent = c.execute("SELECT granted_by FROM consents WHERE user_id = %s",
                            (cid,)).fetchone()
    assert str(rep["user_id"]) == cid and rep["uploaded_by"] == manager[2]
    assert consent["granted_by"] == manager[2]
    listed = client.get("/api/family").json()
    assert [(m["member_id"], m["status"], m["name"]) for m in listed["members"]] == [
        (cid, "active", "Mira")]


def test_query_param_profile_works_like_the_header(client, manager):
    cid = _add_child(client)["member_id"]
    assert client.get(f"/api/me?profile={cid}").json()["id"] == cid
    assert client.get("/api/me?profile=nonsense").status_code == 404


def test_adult_invite_pending_until_accepted(client, manager, adult):
    ac, aid = adult
    r = _invite(client)
    assert r.status_code == 201 and r.json()["status"] == "pending"
    assert r.json()["member_id"] == str(aid)  # the existing patient is reused
    assert client.get("/api/me", headers=_as(aid)).status_code == 404
    invites = ac.get("/api/family").json()["invites"]
    assert [(i["link_id"], i["status"]) for i in invites] == [(r.json()["link_id"], "pending")]
    # only the member accepts
    assert client.post(f"/api/family/{r.json()['link_id']}/accept").status_code == 404
    assert ac.post(f"/api/family/{r.json()['link_id']}/accept").status_code == 200
    assert client.get("/api/me", headers=_as(aid)).json()["id"] == str(aid)
    # a second invite to the same person is a conflict, not a duplicate
    assert _invite(client).status_code == 409


def test_invite_new_phone_creates_patient_who_can_sign_in(client, manager, login):
    r = _invite(client, phone="9822222222")
    assert r.status_code == 201
    with TestClient(client.app) as nc:
        assert login(manager[0], "9822222222", c=nc).status_code == 200
        assert nc.get("/api/me").json()["id"] == r.json()["member_id"]


def test_invite_validation(client, manager):
    assert _invite(client, phone="12").json() == {"error": "invalid_phone"}
    assert client.post("/api/family", json={"relation": "spouse", "name": "X"}).status_code == 422
    assert _invite(client, phone=MANAGER).status_code == 409  # yourself
    make_user(manager[1], "+919100000999", "lab_staff")
    r = _invite(client, phone="+919100000999")
    assert r.status_code == 409 and r.json() == {"error": "not_a_patient"}


def test_member_without_consent_cannot_upload(client, manager, adult):
    ac, aid = adult
    ac.post(f"/api/family/{_invite(client).json()['link_id']}/accept")
    r = client.post("/api/reports", files=PDF, headers=_as(aid))
    assert r.status_code == 403 and r.json() == {"error": "consent_required"}
    # the manager cannot consent on the adult's behalf
    assert client.post("/api/consents", json=CONSENT, headers=_as(aid)).status_code == 404
    assert ac.post("/api/consents", json=CONSENT).status_code == 201
    assert client.post("/api/reports", files=PDF, headers=_as(aid)).status_code == 201


def test_revoked_link_404_immediately(client, manager, adult):
    ac, aid = adult
    link = _invite(client).json()["link_id"]
    ac.post(f"/api/family/{link}/accept")
    assert client.get("/api/reports", headers=_as(aid)).status_code == 200
    assert ac.delete(f"/api/family/{link}").status_code == 204  # the member revokes
    assert client.get("/api/reports", headers=_as(aid)).status_code == 404
    assert client.get("/api/me", headers=_as(aid)).status_code == 404
    assert client.delete(f"/api/family/{link}").status_code == 404  # already revoked
    # re-inviting after a revoke starts a fresh pending link
    assert _invite(client).json()["status"] == "pending"


def test_manager_revokes_child(client, manager):
    child = _add_child(client)
    assert client.delete(f"/api/family/{child['link_id']}").status_code == 204
    assert client.get("/api/me", headers=_as(child["member_id"])).status_code == 404


def test_profile_header_for_stranger_is_404(client, manager, adult):
    _, aid = adult
    for value in (str(aid), str(uuid.uuid4()), "not-a-uuid", str(manager[2])):
        assert client.get("/api/reports", headers={"X-Profile": value}).status_code == 404


def test_member_cannot_act_for_manager(client, manager, adult):
    ac, aid = adult
    ac.post(f"/api/family/{_invite(client).json()['link_id']}/accept")
    assert ac.get("/api/me", headers=_as(manager[2])).status_code == 404


def test_staff_cannot_use_profiles(client, manager, login):
    cid = _add_child(client)["member_id"]
    with TestClient(client.app) as sc:
        make_user(manager[1], "+919100000998", "lab_staff")
        login(manager[0], "+919100000998", c=sc)
        assert sc.get("/api/staff/reports", headers=_as(cid)).status_code == 404
        assert sc.get("/api/family").status_code == 404


def test_cross_tenant_member_is_404(client, manager, login, lab):
    from app import crypto

    other = f"lab-{uuid.uuid4().hex[:8]}"
    crypto.provision_tenant(other, other)
    with TestClient(client.app) as oc:
        login(other, "9833333333", c=oc)
        foreign = _add_child(oc)["member_id"]
        foreign_link = oc.get("/api/family").json()["members"][0]["link_id"]
        assert client.get("/api/me", headers=_as(foreign)).status_code == 404
        assert client.delete(f"/api/family/{foreign_link}").status_code == 404


def test_delete_me_and_export_refuse_profile_header(client, manager):
    cid = _add_child(client)["member_id"]
    h = _as(cid)
    assert client.get("/api/me/export", headers=h).status_code == 404
    assert client.delete("/api/me", headers=h).status_code == 404
    assert client.delete("/api/consents/core", headers=h).status_code == 404
    assert client.get("/api/family", headers=h).status_code == 404
    assert client.post("/api/family", json=CHILD, headers=h).status_code == 404
    with _owner(manager[1]) as c:
        assert c.execute("SELECT 1 FROM users WHERE id = %s", (cid,)).fetchone() is not None
    assert client.get("/api/me/export").status_code == 200  # own export still works


def test_audit_records_manager_as_actor(client, manager):
    cid = _add_child(client)["member_id"]
    client.get("/api/reports", headers=_as(cid))
    with _owner(manager[1]) as c:
        row = c.execute(
            "SELECT actor_user_id FROM audit_log WHERE action = 'list' AND entity = 'report' "
            "AND entity_id = %s", (cid,)).fetchone()
    assert row["actor_user_id"] == manager[2]


def test_child_cannot_be_given_a_phone_later(client, manager):
    r = client.post("/api/family", json={**CHILD, "phone": "9844444444"})
    assert r.status_code == 422
    cid = _add_child(client)["member_id"]
    assert client.patch(f"/api/family/{cid}", json={"phone": "9844444444"}).status_code in (
        404, 405)
    with _owner(manager[1]) as c:
        u = c.execute("SELECT phone_fp, phone_enc FROM users WHERE id = %s", (cid,)).fetchone()
    assert u["phone_fp"] is None and u["phone_enc"] is None


def test_child_needs_consent_version(client, manager):
    r = client.post("/api/family", json={"relation": "child", "name": "Mira"})
    assert r.status_code == 422


def test_manager_delete_removes_sole_managed_children(client, manager, login):
    kept = _add_child(client, "Kept")["member_id"]
    gone = _add_child(client, "Gone")["member_id"]
    with TestClient(client.app) as oc:  # a second manager also holds `kept`
        login(manager[0], "9855555555", c=oc)
        oid = uuid.UUID(oc.get("/api/me").json()["id"])
        with _owner(manager[1]) as c:
            c.execute("INSERT INTO family_links (tenant_id, manager_id, member_id, relation, "
                      "status) VALUES (%s, %s, %s, 'child', 'active')", (manager[1], oid, kept))
        rid = client.post("/api/reports", files=PDF, headers=_as(gone)).json()["id"]
        assert client.delete("/api/me").status_code == 204
    with _owner(manager[1]) as c:
        ids = {str(r["id"]) for r in c.execute("SELECT id FROM users")}
        jobs = c.execute("SELECT count(*) AS n FROM jobs WHERE payload->>'report_id' = %s",
                         (rid,)).fetchone()["n"]
    assert kept in ids and gone not in ids
    assert jobs == 2  # the upload's job plus the delete's cleanup job


def test_pipeline_runs_for_a_phoneless_child(client, manager):
    with psycopg.connect(settings.worker_database_url, row_factory=dict_row) as c:
        c.execute("UPDATE jobs SET status = 'done' WHERE status IN ('queued', 'running')")
    cid = _add_child(client)["member_id"]
    rid = client.post("/api/reports", files=PDF, headers=_as(cid)).json()["id"]
    assert worker.run_once(_models()) is True
    assert client.get(f"/api/reports/{rid}", headers=_as(cid)).json()["status"] == "ready"


def test_staff_list_shows_child_report_without_phone(client, manager, login):
    cid = _add_child(client)["member_id"]
    rid = client.post("/api/reports", files=PDF, headers=_as(cid)).json()["id"]
    with TestClient(client.app) as sc:
        make_user(manager[1], "+919100000997", "lab_staff")
        login(manager[0], "+919100000997", c=sc)
        row = next(x for x in sc.get("/api/staff/reports").json() if x["id"] == rid)
    assert row["phone_masked"] is None and row["name"] == "Mira"


def test_pending_invite_never_reveals_the_members_stored_name(client, manager):
    make_user(manager[1], "9866666666", "patient", name="Lab Entered Name")
    r = _invite(client, phone="9866666666")
    assert r.status_code == 201
    body = client.get("/api/family").text
    assert "Lab Entered Name" not in body
    members = client.get("/api/family").json()["members"]
    assert [m["name"] for m in members] == ["Papa"]  # the manager's own label


def test_label_stays_after_accept(client, manager, adult):
    ac, aid = adult
    with _owner(manager[1]) as c:
        from app import crypto
        cipher = crypto.cipher_for(c, manager[1])
        c.execute("UPDATE users SET name_enc = %s WHERE id = %s",
                  (cipher.encrypt("Real Name"), aid))
    ac.post(f"/api/family/{_invite(client).json()['link_id']}/accept")
    assert [m["name"] for m in client.get("/api/family").json()["members"]] == ["Papa"]


def test_invited_unknown_phone_gets_no_name(client, manager):
    mid = _invite(client, phone="9877777777").json()["member_id"]
    with _owner(manager[1]) as c:
        u = c.execute("SELECT name_enc FROM users WHERE id = %s", (mid,)).fetchone()
    assert u["name_enc"] is None


def test_existing_users_name_is_never_touched(client, manager):
    uid = make_user(manager[1], "9866666667", "patient")
    _invite(client, phone="9866666667")
    with _owner(manager[1]) as c:
        assert c.execute("SELECT name_enc FROM users WHERE id = %s",
                         (uid,)).fetchone()["name_enc"] is None


def test_removing_a_child_deletes_the_child(client, manager):
    child = _add_child(client)
    rid = client.post("/api/reports", files=PDF, headers=_as(child["member_id"])).json()["id"]
    assert client.delete(f"/api/family/{child['link_id']}").status_code == 204
    with _owner(manager[1]) as c:
        assert c.execute("SELECT 1 FROM users WHERE id = %s",
                         (child["member_id"],)).fetchone() is None
        assert c.execute("SELECT 1 FROM reports WHERE id = %s", (rid,)).fetchone() is None
    assert client.get("/api/family").json()["members"] == []


def test_removing_a_child_with_another_manager_keeps_it(client, manager, login):
    child = _add_child(client)
    with TestClient(client.app) as oc:
        login(manager[0], "9855555556", c=oc)
        oid = uuid.UUID(oc.get("/api/me").json()["id"])
        with _owner(manager[1]) as c:
            c.execute("INSERT INTO family_links (tenant_id, manager_id, member_id, relation, "
                      "status) VALUES (%s, %s, %s, 'child', 'active')",
                      (manager[1], oid, child["member_id"]))
        assert client.delete(f"/api/family/{child['link_id']}").status_code == 204
        assert oc.get("/api/me", headers=_as(child["member_id"])).status_code == 200
    with _owner(manager[1]) as c:
        assert c.execute("SELECT 1 FROM users WHERE id = %s",
                         (child["member_id"],)).fetchone() is not None


def test_pending_invites_are_capped(client, manager):
    for i in range(10):
        assert _invite(client, phone=f"98880000{i:02d}").status_code == 201
    r = _invite(client, phone="9888000099")
    assert r.status_code == 429 and r.json() == {"error": "too_many_invites"}


def test_revoke_kills_the_managers_share_links_for_the_member(client, manager, adult):
    """A removed manager must not keep reading the member's reports through a share link."""
    from tests.test_share import _share, _view
    from tests.test_trends_store import _store

    ac, aid = adult
    link = _invite(client).json()["link_id"]
    ac.post(f"/api/family/{link}/accept")
    theirs = _store((manager[1], aid), glucose=90)
    url = _share(client, [theirs], headers=_as(aid)).json()["url"]
    own = _share(ac, [theirs]).json()["url"]  # the member's own link stays
    assert _view(url).status_code == 200
    assert ac.delete(f"/api/family/{link}").status_code == 204
    assert _view(url).status_code == 404
    assert _view(own).status_code == 200
