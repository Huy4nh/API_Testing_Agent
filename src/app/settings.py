from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str

    database_url: str
    redis_url: str

    telegram_api_id: int
    telegram_api_hash: str

    sessions_dir: str = "./sessions"


settings = Settings()