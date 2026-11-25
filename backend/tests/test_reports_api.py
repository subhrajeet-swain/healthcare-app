import uuid

from fastapi.testclient import TestClient

from app import db, files
from app.config import settings
from app.main import app
from tests.conftest import CONSENT, pdf_bytes

PDF = ("r.pdf", pdf_bytes(), "application/pdf")
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 64


def _upload(client, file=PDF):
    return client.post("/api/reports", files={"file": file})


def _owner(tid):
    return db.owner_tx(settings.owner_database_url, tid)


def test_sniff_accepts_pdf_jpeg_png():
    assert files.sniff(pdf_bytes()) == "application/pdf"
    assert files.sniff(PNG) == "image/png"
    assert files.sniff(JPEG) == "image/jpeg"


def test_html_named_pdf_rejected(client, patient):
    r = _upload(client, ("x.pdf", b"<html><script>alert(1)</script>", "application/pdf"))
    assert r.status_code == 415 and r.json() == {"error": "unsupported_file"}


def test_exe_named_pdf_rejected(client, patient):
    r = _upload(client, ("x.pdf", b"MZ\x90\x00" + b"\0" * 64, "application/pdf"))
    assert r.status_code == 415


def test_too_large_is_413(client, patient):
    big = b"%PDF-" + b"\0" * files.MAX_BYTES
    r = _upload(client, ("x.pdf", big, "application/pdf"))
    assert r.status_code == 413 and r.json() == {"error": "file_too_large"}


def test_pdf_over_max_pages_is_422(client, patient):
    r = _upload(client, ("x.pdf", pdf_bytes(files.MAX_PAGES + 1), "application/pdf"))
    assert r.status_code == 422 and r.json() == {"error": "unreadable_file"}


def test_broken_pdf_is_422(client, patient):
    r = _upload(client, ("x.pdf", b"%PDF-1.7 garbage", "application/pdf"))
    assert r.status_code == 422 and r.json() == {"error": "unreadable_file"}


def test_upload_requires_login(client):
    assert _upload(client).status_code == 401


def test_upload_requires_consent(client, lab, login):
    login(lab[0])
    r = _upload(client)
    assert r.status_code == 403 and r.json() == {"error": "consent_required"}


def test_upload_creates_received_report_and_job(client, patient):
    _, tid, _ = patient
    r = _upload(client)
    assert r.status_code == 201
    rid = r.json()["id"]
    assert r.json()["status"] == "received"
    d = client.get(f"/api/reports/{rid}").json()
    assert d["status"] == "received" and [s["status"] for s in d["steps"]] == ["received"]
    assert d["results"] == [] and d["explanations"] == {}
    with _owner(tid) as c:
        jobs = c.execute("SELECT kind, payload, status FROM jobs").fetchall()
    assert [(j["kind"], j["payload"], j["status"]) for j in jobs] == [
        ("report.pipeline", {"report_id": rid}, "queued")
    ]
    listed = client.get("/api/reports").json()
    assert [x["id"] for x in listed] == [rid] and listed[0]["source"] == "patient"


def test_image_upload_accepted(client, patient):
    r = _upload(client, ("photo.png", PNG, "image/png"))
    assert r.status_code == 201


def test_file_on_disk_is_encrypted(client, patient):
    _, tid, _ = patient
    rid = _upload(client).json()["id"]
    raw = (settings.storage_dir / str(tid) / rid).read_bytes()
    assert b"%PDF" not in raw and raw != PDF[1]


def test_file_endpoint_serves_sniffed_mime_no_store(client, patient):
    rid = _upload(client, ("x.jpg", PNG, "image/jpeg")).json()["id"]  # client lies about type
    r = client.get(f"/api/reports/{rid}/file")
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_other_patient_gets_404_on_report_and_file(client, patient, login):
    slug = patient[0]
    rid = _upload(client).json()["id"]
    with TestClient(app) as other:
        login(slug, "9876500000", c=other)
        other.post("/api/consents", json=CONSENT)
        for url in (f"/api/reports/{rid}", f"/api/reports/{rid}/file"):
            r = other.get(url)
            assert r.status_code == 404 and r.json() == {"error": "not_found"}, url
        assert other.get("/api/reports").json() == []


def test_unknown_report_404(client, patient):
    assert client.get(f"/api/reports/{uuid.uuid4()}").status_code == 404


def test_report_read_is_audited(client, patient):
    _, tid, _ = patient
    rid = _upload(client).json()["id"]
    client.get(f"/api/reports/{rid}")
    client.get(f"/api/reports/{rid}/file")
    with _owner(tid) as c:
        rows = c.execute(
            "SELECT action, entity FROM audit_log WHERE entity_id = %s ORDER BY id", (rid,)
        ).fetchall()
    assert [(r["action"], r["entity"]) for r in rows] == [
        ("create", "report"), ("read", "report"), ("read", "report_file")
    ]


def test_delete_me_removes_report_files(client, patient):
    _, tid, _ = patient
    rid = _upload(client).json()["id"]
    path = settings.storage_dir / str(tid) / rid
    assert path.exists()
    assert client.delete("/api/me").status_code == 204
    assert not path.exists()
    with _owner(tid) as c:
        assert c.execute("SELECT count(*) AS n FROM reports").fetchone()["n"] == 0


def test_export_includes_reports(client, patient):
    rid = _upload(client).json()["id"]
    data = client.get("/api/me/export").json()
    assert [r["id"] for r in data["reports"]] == [rid]
    assert data["reports"][0]["results"] == []
