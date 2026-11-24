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
