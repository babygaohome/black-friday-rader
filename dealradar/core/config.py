from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DEALRADAR_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./dealradar.db"
    redis_url: str = "redis://localhost:6379/0"
    event_mode: str = "NORMAL"  # NORMAL | BLACK_FRIDAY
    telegram_bot_token: str = ""
    secret_key: str = "dev-only-change-me"  # signs session tokens; set DEALRADAR_SECRET_KEY in production
    token_ttl_seconds: int = 7 * 24 * 3600


def get_settings() -> Settings:
    return Settings()
