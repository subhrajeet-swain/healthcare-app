import os

from cryptography.fernet import Fernet

# Test settings, set before any app module is imported.
os.environ.setdefault("ENV", "test")
os.environ.setdefault("MASTER_KEY", Fernet.generate_key().decode())
os.environ.setdefault("OTP_PEPPER", "test-pepper")
for var, role, pw in [
    ("DATABASE_URL", "hc_app", "app_dev"),
    ("OWNER_DATABASE_URL", "hc_owner", "owner_dev"),
    ("GRAPH_DATABASE_URL", "hc_graph", "graph_dev"),
    ("WORKER_DATABASE_URL", "hc_worker", "worker_dev"),
]:
    os.environ.setdefault(var, f"postgresql://{role}:{pw}@localhost:5433/hc_test")
os.environ.setdefault(
    "ADMIN_DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/postgres"
)


import psycopg  # noqa: E402
import pytest  # noqa: E402

from app import migrate  # noqa: E402
from app.config import settings  # noqa: E402


@pytest.fixture(scope="session")
def db_urls():
    """Fresh hc_test database, migrated, for the whole test session."""
    with psycopg.connect(settings.admin_database_url, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS hc_test WITH (FORCE)")
        admin.execute("CREATE DATABASE hc_test OWNER hc_owner")
    migrate.run(settings.owner_database_url, settings.graph_database_url)
    return {
        "app": settings.database_url,
        "owner": settings.owner_database_url,
        "graph": settings.graph_database_url,
    }


import logging  # noqa: E402
import re  # noqa: E402
import uuid  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(db_urls):
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def lab(db_urls):
    """A fresh tenant; returns (slug, tenant_id)."""
    from app import crypto

    slug = f"lab-{uuid.uuid4().hex[:8]}"
    return slug, crypto.provision_tenant(slug, slug)


@pytest.fixture
def login(client, caplog):
    """login(slug, phone) -> response of a full OTP login on `client`."""
    caplog.set_level(logging.INFO, logger="app.auth")

    def _login(slug, phone="9876543210", c=None):
        c = c or client
        caplog.clear()
        assert c.post(f"/api/auth/{slug}/otp", json={"phone": phone}).status_code == 202
        code = re.search(r"OTP for \S+: (\d{6})", caplog.text).group(1)
        return c.post(f"/api/auth/{slug}/verify", json={"phone": phone, "code": code})

    return _login
