"""Two labs with staff, patients and canary records. Idempotent: existing labs are left alone.

The phone +919000000001 is a patient at BOTH labs (two separate users), which the canary
tests use to prove the labs never merge.
"""

from uuid import UUID

from app import crypto, db
from app.config import settings

SHARED_PHONE = "+919000000001"

LABS = {
    "lab-alpha": ("Alpha Diagnostics", "ALPHA-7319", "91"),
    "lab-beta": ("Beta Pathlabs", "BETA-4826", "92"),
}


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
        out[f"{slug}:shared"] = shared["id"]
    return out


if __name__ == "__main__":
    for k, v in run().items():
        print(f"{k}: {v}")
