from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# here the env is loaded and validated.
class Settings(BaseSettings):
    # SettingsConfigDict - defines how settings should be loaded. It looks for .env file and pulls value from them.
    # there is no case sensitive, if theres extra fields in .env file and not defined here - ignote them

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ############## Data provider
    # Literal - acts as a whitelist.
    data_provider: Literal["yfinance", "alpha_vantage", "polygon"] = "yfinance"
    alpha_vantage_key: str | None = None
    polygon_key: str | None = None

    ############## LLM (BYOK)
    llm_api_key: str | None = None
    llm_model: str = "claude-sonnet-4-20250514"
    llm_provider: Literal["anthropic", "openai", "groq"] = "anthropic"

    ############## Langfuse monitoring
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None

    ############# MCP Transport
    mcp_transport: Literal["stdio", "http"] = "stdio"
    mcp_http_port: int = 8000
    mcp_http_api_key: str | None = None

    ##########Feature flags
    ai_chat_enabled: bool = True
    serve_stale_only: bool = False
    validation_mode: Literal["strict", "warm_only"] = "strict"

    ##########Rate limiting
    rate_limit_per_min: int = 60

    ########Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "text"

    # ── Database ───────────────────────────────────────────────────────────────
    # Railway sets DATABASE_URL automatically for PostgreSQL addon

    # aliaschoices is used -to be dynamic with production env. Look for DATABASE_URL first, if thats not there - look for database_url.
    database_url: str = Field(
        default="sqlite+aiosqlite:///./investorai.db",
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
    )

    # ── Server ─────────────────────────────────────────────────────────────────
    port: int = Field(default=8000, validation_alias=AliasChoices("PORT", "port"))
    host: str = "0.0.0.0"


# class instantiated - this happens at module level, but you can import settings anywhere in the app - and it will contain
# loaded and validated ready-to-use configuration.
settings = Settings()
