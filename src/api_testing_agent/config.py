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

    testcase_generator_mode: str = Field(default="rule", alias="TESTCASE_GENERATOR_MODE")

    # Có thể để dạng "openai:gpt-5.2" hoặc chỉ "gpt-5.2"
    langchain_model_name: str = Field(default="openai:gpt-5.2", alias="LANGCHAIN_MODEL_NAME")

    # Tùy chọn. Nếu không set, code có thể để LangChain tự suy ra provider.
    langchain_model_provider: str | None = Field(default=None, alias="LANGCHAIN_MODEL_PROVIDER")

    langgraph_checkpointer: str = Field(default="memory", alias="LANGGRAPH_CHECKPOINTER")
    langgraph_sqlite_path: str = Field(
        default="./data/langgraph_checkpoints.db",
        alias="LANGGRAPH_SQLITE_PATH",
    )
    default_language_policy: str = "adaptive"
    default_language: str = "vi"