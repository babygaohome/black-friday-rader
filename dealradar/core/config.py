from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DEALRADAR_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./dealradar.db"
    redis_url: str = "redis://localhost:6379/0"
    event_mode: str = "NORMAL"  # NORMAL | BLACK_FRIDAY
    telegram_bot_token: str = ""


def get_settings() -> Settings:
    return Settings()
