import uuid

import pytest
from cryptography.fernet import InvalidToken

from app import crypto, db


@pytest.fixture
def tenants(db_urls):
    a = crypto.provision_tenant(f"c-a-{uuid.uuid4().hex[:8]}", "A")
    b = crypto.provision_tenant(f"c-b-{uuid.uuid4().hex[:8]}", "B")
    ciphers = {}
    for tid in (a, b):
        with db.owner_tx(db_urls["owner"], tid) as c:
            ciphers[tid] = crypto.cipher_for(c, tid)
    return ciphers[a], ciphers[b], a


@pytest.mark.parametrize(
    "raw", ["98765 43210", "+91-98765-43210", "09876543210", "+919876543210", "(98765) 43210"]
)
def test_phone_formats_normalise_equal(raw):
    assert crypto.normalise_phone(raw) == "+919876543210"


@pytest.mark.parametrize("raw", ["12345", "abcdefghij", "", "+1 202 555 0100", "1234567890"])
def test_invalid_phone_rejected(raw):
    with pytest.raises(ValueError):
        crypto.normalise_phone(raw)


def test_encrypt_roundtrip_and_not_plaintext(tenants):
    a, _, _ = tenants
    token = a.encrypt("Ramesh")
    assert b"Ramesh" not in token
    assert a.decrypt(token) == "Ramesh"


def test_same_phone_different_tenants_different_fingerprint(tenants):
    a, b, _ = tenants
    assert a.fingerprint("+919876543210") != b.fingerprint("+919876543210")
    assert a.fingerprint("+919876543210") == a.fingerprint("+919876543210")


def test_other_tenant_cannot_decrypt(tenants):
    a, b, _ = tenants
    with pytest.raises(InvalidToken):
        b.decrypt(a.encrypt("Ramesh"))


def test_tenant_keys_not_stored_in_plaintext(db_urls, tenants):
    a, _, tid = tenants
    with db.owner_tx(db_urls["owner"], tid) as c:
        row = c.execute("SELECT data_key_enc, fp_key_enc FROM tenant_keys").fetchone()
    assert a.data_key not in bytes(row["data_key_enc"])
    assert a.fp_key not in bytes(row["fp_key_enc"])
