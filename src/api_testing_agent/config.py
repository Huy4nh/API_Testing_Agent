from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    target_registry_path: str = Field(default="./targets.json", alias="TARGET_REGISTRY_PATH")
    http_timeout_seconds: float = Field(default=15.0, alias="HTTP_TIMEOUT_SECONDS")
    max_concurrency: int = Field(default=5, alias="MAX_CONCURRENCY")
    sqlite_path: str = Field(default="./data/runs.sqlite3", alias="SQLITE_PATH")
    report_output_dir: str = Field(default="./reports", alias="REPORT_OUTPUT_DIR")
    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
