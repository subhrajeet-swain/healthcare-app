"""Per-tenant encryption for identifying fields, and keyed phone fingerprints for lookup."""

import hashlib
import hmac
import os
import re
import unicodedata
from uuid import UUID

import psycopg
from cryptography.fernet import Fernet

from app import db
from app.config import settings

_INDIAN_MOBILE = re.compile(r"[6-9][0-9]{9}")


def normalise_phone(raw: str) -> str:
    """Indian mobile numbers only, returned as E.164 (+91XXXXXXXXXX)."""
    # Hindi keyboards type Devanagari digits; fold every Unicode digit to ASCII first.
    ascii_ = "".join(str(unicodedata.digit(ch)) if ch.isdigit() else ch for ch in raw)
    digits = re.sub(r"[\s\-()]", "", ascii_)
    for prefix in ("+91", "0091"):
        if digits.startswith(prefix):
            digits = digits[len(prefix) :]
            break
    else:
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
    if not _INDIAN_MOBILE.fullmatch(digits):
        raise ValueError("invalid_phone")
    return "+91" + digits


class TenantCipher:
    def __init__(self, data_key: bytes, fp_key: bytes):
        self.data_key = data_key
        self.fp_key = fp_key
        self._fernet = Fernet(data_key)

    def encrypt(self, text: str) -> bytes:
        return self._fernet.encrypt(text.encode())

    def decrypt(self, token: bytes) -> str:
        return self._fernet.decrypt(bytes(token)).decode()

    def encrypt_bytes(self, data: bytes) -> bytes:
        return self._fernet.encrypt(data)

    def decrypt_bytes(self, token: bytes) -> bytes:
        return self._fernet.decrypt(bytes(token))

    def fingerprint(self, phone_e164: str) -> bytes:
        return hmac.new(self.fp_key, phone_e164.encode(), hashlib.sha256).digest()


def _master() -> Fernet:
    return Fernet(settings.master_key.encode())


def provision_tenant(slug: str, name: str) -> UUID:
    """Create a tenant with a fresh data key and fingerprint key, both wrapped by the master key."""
    with db.owner_tx(settings.owner_database_url) as c:
        tid = c.execute(
            "INSERT INTO tenants (slug, name) VALUES (%s, %s) RETURNING id", (slug, name)
        ).fetchone()["id"]
        db._set_tenant(c, tid)
        c.execute(
            "INSERT INTO tenant_keys (tenant_id, data_key_enc, fp_key_enc) VALUES (%s, %s, %s)",
            (tid, _master().encrypt(Fernet.generate_key()), _master().encrypt(os.urandom(32))),
        )
    return tid


# ponytail: per-process key cache, no eviction; fine for 20 tenants
_cache: dict[UUID, TenantCipher] = {}


def cipher_for(conn: psycopg.Connection, tenant_id: UUID) -> TenantCipher:
    """Reads the tenant's keys inside the caller's (tenant-scoped) transaction."""
    if tenant_id not in _cache:
        row = conn.execute(
            "SELECT data_key_enc, fp_key_enc FROM tenant_keys WHERE tenant_id = %s", (tenant_id,)
        ).fetchone()
        if row is None:
            raise LookupError("tenant_keys_missing")
        m = _master()
        _cache[tenant_id] = TenantCipher(
            m.decrypt(bytes(row["data_key_enc"])), m.decrypt(bytes(row["fp_key_enc"]))
        )
    return _cache[tenant_id]
