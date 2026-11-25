"""Two labs with staff, patients and canary records. Idempotent: existing labs are left alone.

The phone +919000000001 is a patient at BOTH labs (two separate users), which the canary
tests use to prove the labs never merge.
"""

from datetime import date
from uuid import UUID

from app import crypto, db, reports
from app.brain.flags import flag_report
from app.brain.models import ExtractedReport
from app.brain.pipeline import template_result
from app.config import settings
from app.tenancy import TenantCtx

SHARED_PHONE = "+919000000001"

LABS = {
    "lab-alpha": ("Alpha Diagnostics", "ALPHA-7319", "91"),
    "lab-beta": ("Beta Pathlabs", "BETA-4826", "92"),
}

# Demo reports for the shared patient, built without a model. Hemoglobin differs per lab
# (canary values): a leak would show the other lab's number.
CANARY_HB = {"lab-alpha": 11.3, "lab-beta": 12.7}


def _row(test_id, name, value, unit, low, high, flag):
    return {"test_id": test_id, "test_name": name, "value": value, "unit": unit,
            "ref_low": low, "ref_high": high, "printed_flag": flag}


def _demo(slug: str) -> list[ExtractedReport]:
    hb = CANARY_HB[slug]
    return [
        ExtractedReport(collected_on=date(2026, 11, 2), results=[
            _row("cbc.hemoglobin", "Hemoglobin", hb, "g/dL", 13.0, 17.0, "L"),
            _row("cbc.wbc", "WBC Count", 7400, "/uL", 4000, 11000, "N"),
            _row("cbc.platelets", "Platelet Count", 245000, "/uL", 150000, 410000, "N"),
        ]),
        ExtractedReport(collected_on=date(2026, 11, 20), results=[
            _row("hba1c.hba1c", "HbA1c", 5.4, "%", 4.0, 5.6, "N"),
            _row("lft.alt", "ALT (SGPT)", 1050, "U/L", 7, 56, "H"),
        ]),
    ]


def _demo_reports(c, slug: str, tid: UUID, uid: UUID) -> None:
    if c.execute("SELECT 1 FROM reports WHERE user_id = %s AND source = 'lab'", (uid,)).fetchone():
        return  # idempotent
    ctx = TenantCtx(tid, uid, "patient")
    for extracted in _demo(slug):
        rid = reports.create_report(c, ctx, uid, "lab", "received")
        report, _ = flag_report(extracted)
        reports.store_result(c, tid, rid, template_result(report))


def _people(tag: str, prefix: str) -> list[tuple[str, str, str]]:
    """(role, phone, name) for one lab."""
    return [
        ("lab_admin", f"+91{prefix}00000101", f"Admin {tag}"),
        ("doctor", f"+91{prefix}00000102", f"Dr Test {tag}"),
        ("lab_staff", f"+91{prefix}00000103", f"Staff {tag}"),
        ("patient", SHARED_PHONE, f"CANARY-{tag}"),
        ("patient", f"+91{prefix}00000104", f"Patient {tag}"),
    ]


def run() -> dict[str, UUID]:
    out: dict[str, UUID] = {}
    for slug, (name, tag, prefix) in LABS.items():
        with db.owner_tx(settings.owner_database_url) as c:
            row = c.execute("SELECT id FROM tenants WHERE slug = %s", (slug,)).fetchone()
        tid = row["id"] if row else crypto.provision_tenant(slug, name)
        out[slug] = tid
        with db.owner_tx(settings.owner_database_url, tid) as c:
            cipher = crypto.cipher_for(c, tid)
            for role, phone, person in _people(tag, prefix):
                fp = cipher.fingerprint(phone)
                c.execute(
                    "INSERT INTO users (tenant_id, role, phone_fp, phone_enc, name_enc) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (tenant_id, phone_fp) DO NOTHING",
                    (tid, role, fp, cipher.encrypt(phone), cipher.encrypt(person)),
                )
            shared = c.execute(
                "SELECT id FROM users WHERE phone_fp = %s", (cipher.fingerprint(SHARED_PHONE),)
            ).fetchone()
            _demo_reports(c, slug, tid, shared["id"])
        out[f"{slug}:shared"] = shared["id"]
    return out


if __name__ == "__main__":
    for k, v in run().items():
        print(f"{k}: {v}")
