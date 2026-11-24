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
]:
    os.environ.setdefault(var, f"postgresql://{role}:{pw}@localhost:5433/hc_test")
os.environ.setdefault("ADMIN_DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/postgres")


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
