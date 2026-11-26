from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    env: Literal["dev", "test", "prod"]  # required: a missing ENV must never mean dev
    database_url: str
    # Owner/graph roles are for migrations and seeding only; the API process never needs them.
    owner_database_url: str = ""
    graph_database_url: str = ""
    admin_database_url: str = ""
    worker_database_url: str = ""  # worker process only: claims jobs across tenants
    storage_dir: Path = Path("data/files")
    # Up to three Gemini keys from separate accounts (separate quotas), tried in order.
    google_api_key_1: str = ""
    google_api_key_2: str = ""
    google_api_key_3: str = ""
    groq_api_key: str = ""
    extract_model: str = "gemini-3.5-flash-lite"
    explain_model: str = "gemini-3.5-flash-lite"
    chat_model: str = "gemini-3.5-flash-lite"
    groq_model: str = "llama-3.3-70b-versatile"
    master_key: str
    otp_pepper: str
    langsmith_tracing: bool = False
    # Doctor alert mail, e.g. smtp://user:app-password@smtp.gmail.com:587. Empty: logged only.
    smtp_url: str = ""
    app_base_url: str = "http://localhost:5173"


settings = Settings()
