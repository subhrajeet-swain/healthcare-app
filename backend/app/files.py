"""Uploaded report files: type checks by content, encrypted at rest, one folder per tenant.

Paths are built from UUIDs only; a client filename or content type is never trusted.
"""

from __future__ import annotations

import io
from pathlib import Path
from uuid import UUID

from pypdf import PdfReader

from app.config import settings
from app.crypto import TenantCipher
from app.errors import ApiError

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 20
ALLOWED = {
    "application/pdf": b"%PDF-",
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
}


def sniff(data: bytes) -> str:
    for mime, magic in ALLOWED.items():
        if data.startswith(magic):
            return mime
    raise ApiError(415, "unsupported_file")


def check_pdf(data: bytes) -> None:
    try:
        reader = PdfReader(io.BytesIO(data))
        ok = not reader.is_encrypted and 0 < len(reader.pages) <= MAX_PAGES
    except Exception:  # pypdf raises many types on malformed input
        ok = False
    if not ok:
        raise ApiError(422, "unreadable_file")


def scan(data: bytes) -> None:
    # ponytail: no AV yet; ClamAV (clamd INSTREAM) goes here before real users
    return None


def check_bytes(data: bytes) -> str:
    """Size, type by content, PDF sanity, scan. Returns the mime; never trusts the sender."""
    if len(data) > MAX_BYTES:
        raise ApiError(413, "file_too_large")
    mime = sniff(data)
    if mime == "application/pdf":
        check_pdf(data)
    scan(data)
    return mime


def _path(tenant_id: UUID, report_id: UUID) -> Path:
    return settings.storage_dir / str(UUID(str(tenant_id))) / str(UUID(str(report_id)))


def save(cipher: TenantCipher, tenant_id: UUID, report_id: UUID, data: bytes) -> None:
    path = _path(tenant_id, report_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(cipher.encrypt_bytes(data))
    tmp.replace(path)


def load(cipher: TenantCipher, tenant_id: UUID, report_id: UUID) -> bytes:
    return cipher.decrypt_bytes(_path(tenant_id, report_id).read_bytes())


def remove(tenant_id: UUID, report_id: UUID) -> None:
    _path(tenant_id, report_id).unlink(missing_ok=True)
