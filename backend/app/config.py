from decimal import Decimal
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    fred_api_key: str = ""

    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_paper: bool = True

    supabase_url: str = ""
    supabase_anon_key: str = ""

    database_url: str = "postgresql+asyncpg://alpha:alpha@localhost:5432/alpha"
    redis_url: str = "redis://localhost:6379/0"

    env: str = "dev"
    log_level: str = "INFO"

    cache_ttl_fundamentals_s: int = 86_400
    cache_ttl_quotes_s: int = 900
    cache_ttl_haiku_s: int = 300

    equity_risk_premium: Decimal = Field(default=Decimal("0.055"))
    universe: str = "SP500,NDX"

    haiku_model: str = "claude-haiku-4-5-20251001"
    sonnet_model: str = "claude-sonnet-4-6"
    narrative_model: str = "claude-haiku-4-5-20251001"
    risk_model: str = "claude-haiku-4-5-20251001"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
