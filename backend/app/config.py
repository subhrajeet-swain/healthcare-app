from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str
    owner_database_url: str
    graph_database_url: str
    admin_database_url: str = ""
    master_key: str
    otp_pepper: str
    langsmith_tracing: bool = False


settings = Settings()
