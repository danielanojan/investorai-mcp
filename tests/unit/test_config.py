import pytest
from pydantic import ValidationError


def test_settings_load_defaults():
    "settings loads with all defaults when no .env overrides are present"
    from investorai_mcp.config import Settings

    s = Settings()
    assert s.data_provider == "yfinance"
    assert s.mcp_transport == "stdio"
    assert s.ai_chat_enabled is True
    assert s.validation_mode == "strict"
    assert s.log_level == "INFO"
    assert s.rate_limit_per_min == 60


def test_settings_database_url_default():
    from investorai_mcp.config import Settings

    s = Settings()
    assert s.database_url.startswith("sqlite+aiosqlite://")


def test_settings_rejects_invalid_provider():
    from investorai_mcp.config import Settings

    with pytest.raises(ValidationError):
        Settings(mcp_transport="websocket")


def test_settings_rejects_invalid_log_level():
    from investorai_mcp.config import Settings

    with pytest.raises(ValidationError):
        Settings(log_level="VERBOSE")


def test_settings_env_override(monkeypatch):
    """Environment variables override defaults correctly."""
    from investorai_mcp.config import Settings

    monkeypatch.setenv("DATA_PROVIDER", "alpha_vantage")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "30")

    s = Settings()
    assert s.data_provider == "alpha_vantage"
    assert s.log_level == "DEBUG"
    assert s.rate_limit_per_min == 30


# assumes the keys are not added to the .env file, which they shouldn't be for security reasons. If they are added, this test should be updated to check for the expected values instead of None.


def test_settings_optional_keys_default_none():
    from investorai_mcp.config import Settings

    s = Settings()
    assert s.alpha_vantage_key is None
    assert s.polygon_key is None
    assert s.mcp_http_api_key is None
