from typing import Literal


from pydantic_settings import BaseSettings, SettingsConfigDict

#here the env is loaded and validated.
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file = ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    ############## Database
    database_url: str = "sqlite+aiosqlite:///./investorai.db"
    
    ############## Data provider
    data_provider : Literal["yfinance", "alpha_vantage", "polygon"] = "yfinance"
    alpha_vantage_key : str | None = None
    polygon_key : str | None = None
    
    ############# MCP Transport
    mcp_transport: Literal["stdio", "http"] = "stdio"
    mcp_http_port : int = 8000
    mcp_http_api_key : str | None = None
    
    
    ##########Feature flags
    ai_chat_enabled : bool = True
    serve_stale_only : bool = False
    validation_mode : Literal["strict", "warm_only"] = "strict"
    
    ##########Rate limiting
    rate_limit_per_min : int = 60
    
    ########Logging
    log_level : Literal["DEBUG", "INFO", "WaRNING", "ERROR"] = "INFO"
    log_format : Literal["json", "text"] = "text"
    

settings = Settings()
