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
    master_key: str
    otp_pepper: str
    langsmith_tracing: bool = False


settings = Settings()
