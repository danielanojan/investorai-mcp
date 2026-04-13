"""Test for the get_trend_summary MCP tool."""

from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from investorai_mcp.db.cache_manager import CacheResult
from investorai_mcp.db.models import PriceHistory
from investorai_mcp.llm.prompt_builder import PriceSummaryStats

@pytest.fixture(autouse=True)
def register_tools():
    from investorai_mcp.server import _register_tools
    _register_tools()
    
def make_row(d: date, price: float) -> PriceHistory:
    row = MagicMock(spec=PriceHistory)
    row.date = d
    row.adj_close = price
    row.volume = 50_000_000
    return row

def make_cache_result(rows):
    return CacheResult(
        data=rows, 
        is_stale=False,
        data_age_hours=1.0,
        provider_used="yfinance",
    )
    
def make_stats():
    return PriceSummaryStats(
        ticker_symbol="AAPL", 
        range="1Y", 
        start_date= date(2025, 4, 1),
        end_date= date(2026, 3, 28),
        start_price=150.0, 
        end_price=174.32,
        period_run_pct=16.21, 
        high_price=182.50, 
        high_date=date(2025, 12, 15), 
        low_price=142.10,
        low_date=date(2025, 6, 10), 
        avg_price=163.45, 
        avg_daily_volume=55_000_000,
        volatality_pct=24.3,
        trading_days=252,
    )
    
def patch_pipeline(llm_response="AAPL rose 16.21% [source: DB • 2026-03-28]."):
    rows = [
        make_row(date(2025, 4, 1), price=150.0),
        make_row(date(206, 3, 28), price=174.32),
    ]
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_manager = MagicMock()
    mock_manager.ensure_ticker_exists = AsyncMock()
    mock_manager.get_prices = AsyncMock(return_value=make_cache_result(rows))
    
    return (
        patch("investorai_mcp.tools.get_trend_summary.AsyncSessionLocal", 
              return_value=mock_session),
        patch("investorai_mcp.tools.get_trend_summary.CacheManager",
                return_value=mock_manager),
        patch("investorai_mcp.tools.get_trend_summary.call_llm",
              new=AsyncMock(return_value=llm_response)),
    )
    
async def test_unsupported_ticker_returns_error():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    
    result = await get_trend_summary("FAKECROP")
    assert result["error"] is True
    assert result["code"] == "TICKER_NOT_SUPPORTED"
    
    
async def test_returns_summary_text():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    
    p1, p2, p3 = patch_pipeline()
    with p1, p2, p3:
        result = await get_trend_summary("AAPL")
    assert "summary" in result
    assert isinstance(result["summary"], str)
    
async def test_returns_stats_block():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    
    p1, p2, p3 = patch_pipeline()
    with p1, p2, p3:
        result = await get_trend_summary("AAPL")
    assert "stats" in result
    assert "start_price" in result["stats"]
    assert "end_price" in result["stats"]
    assert "period_return_pct" in result["stats"]
    
async def test_return_citations():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    
    p1, p2, p3 = patch_pipeline(
        "AAPL rose [source: DB • 2026-03-28]."
    )
    with p1, p2, p3:
        result = await get_trend_summary("AAPL")
    assert "citations" in result
    assert isinstance(result["citations"], list)
    
async def test_validation_passed_field_piresent():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    
    p1, p2, p3 = patch_pipeline()
    with p1, p2, p3:
        result = await get_trend_summary("AAPL")
    assert "validation_passed" in result

async def test_llm_unavilable_returns_error():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    
    rows = [make_row(date(2025, 4, 1), 150.0),
            make_row(date(2026, 3, 28), 174.32)]
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_manager = MagicMock()
    mock_manager.ensure_ticker_exists = AsyncMock()
    mock_manager.get_prices = AsyncMock(return_value=make_cache_result(rows))
    
    with patch("investorai_mcp.tools.get_trend_summary.AsyncSessionLocal",
                return_value=mock_session), \
        patch("investorai_mcp.tools.get_trend_summary.CacheManager",
                  return_value=mock_manager), \
        patch("investorai_mcp.tools.get_trend_summary.call_llm",
              new=AsyncMock(side_effect=RuntimeError("no key"))):
        result = await get_trend_summary("AAPL")
    assert result["error"] is True
    assert result["code"] == "LLM_UNAVILABLE"
    
async def test_empty_data_returns_error():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_manager = MagicMock()
    mock_manager.ensure_ticker_exists = AsyncMock()
    mock_manager.get_prices = AsyncMock(return_value=make_cache_result([]))
    
    with patch("investorai_mcp.tools.get_trend_summary.AsyncSessionLocal",
                return_value=mock_session), \
        patch("investorai_mcp.tools.get_trend_summary.CacheManager",
                    return_value=mock_manager):
        result = await get_trend_summary("AAPL")
    assert result["error"] is True
