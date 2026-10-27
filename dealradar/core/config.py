from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DEALRADAR_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./dealradar.db"
    redis_url: str = "redis://localhost:6379/0"
    event_mode: str = "NORMAL"  # NORMAL | BLACK_FRIDAY
    deal_min_score: int = 85  # deal.created threshold in NORMAL mode
    black_friday_deal_min_score: int = 90  # stricter in BLACK_FRIDAY mode (assumption, see publisher.py)
    telegram_bot_token: str = ""
    amazon_paapi_access_key: str = ""
    amazon_paapi_secret_key: str = ""
    amazon_paapi_partner_tag: str = ""  # Associates tag; Amazon AU is only enabled when all three are set
    cors_origins: str = "http://localhost:3000"  # comma separated; the Next.js frontend origin(s)
    log_level: str = "INFO"
    secret_key: str = "dev-only-change-me"  # signs session tokens; set DEALRADAR_SECRET_KEY in production
    token_ttl_seconds: int = 7 * 24 * 3600


def get_settings() -> Settings:
    return Settings()
