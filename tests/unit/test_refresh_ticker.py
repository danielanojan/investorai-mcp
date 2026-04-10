""" Tests for the refresh ticker MCP tool"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from investorai_mcp.db.cache_manager import CacheResult

@pytest.fixture(autouse=True)
def register_tools():
    from investorai_mcp.server import _register_tools
    _register_tools()

@pytest.fixture(autouse=True)
def clear_rate_limit():
    """Reset in-memory rate limit dict before every test"""
    import investorai_mcp.tools.refresh_ticker as rt 
    rt._last_refresh.clear()
    yield
    rt._last_refresh.clear()
    
def make_cache_result(n_rows=100):
    rows = [MagicMock() for _ in range(n_rows)]
    return CacheResult(
        data=rows, 
        is_stale=False,
        data_age_hours=0.0,
        provider_used="yfinance",
    )
    
def patch_manager(result=None):
    if result is None:
        result = make_cache_result()
    manager = MagicMock()
    manager.ensure_ticker_exists = AsyncMock(return_value=MagicMock())
    manager.force_refresh_prices = AsyncMock(return_value=result)
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return (
        patch("investorai_mcp.tools.refresh_ticker.AsyncSessionLocal", return_value=mock_session),
        patch("investorai_mcp.tools.refresh_ticker.CacheManager", return_value=manager),
        manager,
    )

async def test_unsupported_ticker_returns_error():
    from investorai_mcp.tools.refresh_ticker import refresh_ticker
    
    result = await refresh_ticker("FAKECROP")
    assert result["error"] is True
    assert result["code"] == "TICKER_NOT_SUPPORTED"

async def test_successful_refresh_returns_success():
    from investorai_mcp.tools.refresh_ticker import refresh_ticker
    
    p1, p2, _ = patch_manager()
    with p1, p2:
        result = await refresh_ticker("AAPL")
    assert result["success"] is True
    assert result["symbol"] == "AAPL"

async def test_refresh_returns_record_count():
    from investorai_mcp.tools.refresh_ticker import refresh_ticker
    
    cache_result = make_cache_result(n_rows=1825) # 5 years of daily data
    p1, p2, _ = patch_manager(result=cache_result)
    with p1, p2:
        result = await refresh_ticker("AAPL")
    assert result["records_loaded"] == 1825
    
async def test_rate_limit_blocks_second_call():
    from investorai_mcp.tools.refresh_ticker import refresh_ticker
    
    p1, p2, _ = patch_manager()
    with p1, p2:
        await refresh_ticker("AAPL")  # First call should succeed
        result = await refresh_ticker("AAPL")  # Second call should be rate limited
    assert result["error"] is True
    assert result["code"] == "RATE_LIMITED"
    assert "retry_after_seconds" in result
    
async def test_rate_limit_allows_after_window():
    from investorai_mcp.tools.refresh_ticker import refresh_ticker
    import investorai_mcp.tools.refresh_ticker as rt
    
    #simulate last refresh was 6 minutes ago
    rt._last_refresh["AAPL"] = (datetime.now(timezone.utc) - timedelta(seconds=360))
    
    p1, p2, _ = patch_manager()
    with p1, p2:
        result = await refresh_ticker("AAPL")  # Should succeed since we're past the rate limit window
    assert result["success"] is True
    
async def test_different_tickers_independent_rate_limits():
    from investorai_mcp.tools.refresh_ticker import refresh_ticker
    
    p1, p2, _ = patch_manager()
    with p1, p2:
        await refresh_ticker("AAPL")  # First call for AAPL
        result = await refresh_ticker("TSLA")  # different ticker - not rate limited
    assert result["success"] is True

async def test_symbol_normalised_uppercase():
    from investorai_mcp.tools.refresh_ticker import refresh_ticker
    
    p1, p2, _ = patch_manager()
    with p1, p2:
        result = await refresh_ticker("aapl")
    assert result["symbol"] == "AAPL"

async def test_refresh_returns_timestamp():
    from investorai_mcp.tools.refresh_ticker import refresh_ticker
    
    p1, p2, _ = patch_manager()
    with p1, p2:
        result = await refresh_ticker("AAPL")
    assert "refreshed_at" in result
    #should be a valid ISO datetime string
    datetime.fromisoformat(result["refreshed_at"])