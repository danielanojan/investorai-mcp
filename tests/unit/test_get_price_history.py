from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from investorai_mcp.data.base import OHLCVRecord
from investorai_mcp.db.cache_manager import CacheResult
from investorai_mcp.db.models import PriceHistory


@pytest.fixture(autouse=True)
def register_tools():
    """Ensure tools are registered before each test so we can call them directly"""
    from investorai_mcp.server import _register_tools
    _register_tools()
    
    
def make_price_row(d: date, price:float = 174.0) -> PriceHistory:
    row = MagicMock(spec=PriceHistory)
    row.date           = d
    row.adj_close      = price
    row.avg_price      = round((price *0.99 + price + price * 0.98 + price ) / 4, 4)
    row.close          = price
    row.volume         = 50_000_000
    return row


def make_cache_result(rows, is_stale=False, age_hours=1.0):
    return CacheResult(
        data=rows, 
        is_stale=is_stale,
        data_age_hours=age_hours,
        provider_used="yfinance",
    )
    
@pytest.fixture
def mock_cache_manager():
    """Patches CacheManager so no real DB or yfinance is needed"""
    rows = [
        make_price_row(date(2026, 1, 1), price=170.0),
        make_price_row(date(2026, 2, 1), price=174.0),
        make_price_row(date(2026, 3, 1), price=178.0),
    ]
    cache_result = make_cache_result(rows)
    
    manager = MagicMock()
    manager.ensure_ticker_exists = AsyncMock(return_value=MagicMock())
    manager.get_prices = AsyncMock(return_value=cache_result)
    
    return manager, rows

async def test_unsupported_ticker_returns_error():
    from investorai_mcp.tools.get_price_history import get_price_history
    
    result = await get_price_history("FAKECROP")
    assert result["error"] is True
    assert result["code"] == "TICKER_NOT_SUPPORTED"
    
async def test_unsupported_ticker_lowercase():
    from investorai_mcp.tools.get_price_history import get_price_history
    
    result = await get_price_history("fakecrop")
    assert result["error"] is True

async def test_returns_prices_list(mock_cache_manager):
    from investorai_mcp.tools.get_price_history import get_price_history
    
    manager, rows = mock_cache_manager
    mock_session = AsyncMock()
    
    mock_session.__aenter__ = AsyncMock(return_value = mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    
    with patch("investorai_mcp.tools.get_price_history.AsyncSessionLocal",
                return_value=mock_session), \
            patch("investorai_mcp.tools.get_price_history.CacheManager",
                     return_value=manager):
            result = await get_price_history("AAPL", range="1Y")
            
    assert "prices" in result
    assert len(result["prices"]) == 3
    assert result["total_days"] == 3
    
    
async def test_price_fields_present(mock_cache_manager):
    from investorai_mcp.tools.get_price_history import get_price_history
    
    manager, _ = mock_cache_manager
    mock_session = AsyncMock()
    
    mock_session.__aenter__ = AsyncMock(return_value = mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    
    with patch("investorai_mcp.tools.get_price_history.AsyncSessionLocal",
                return_value=mock_session), \
            patch("investorai_mcp.tools.get_price_history.CacheManager",
                        return_value=manager):
            result = await get_price_history("AAPL")
            
    first = result["prices"][0]
    for field in ["date", "price", "adj_close", "avg_price", "volume"]:
        assert field in first, f"Expected field '{field}' not found in price record"
        
async def test_summary_statistics_computed(mock_cache_manager):
    from investorai_mcp.tools.get_price_history import get_price_history
    
    manager, _ = mock_cache_manager
    mock_session = AsyncMock()
    
    mock_session.__aenter__ = AsyncMock(return_value = mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    
    with patch("investorai_mcp.tools.get_price_history.AsyncSessionLocal",
                return_value=mock_session), \
            patch("investorai_mcp.tools.get_price_history.CacheManager",
                        return_value=manager):
            result = await get_price_history("AAPL")
            
    assert result["start_price"] == 170.0
    assert result["end_price"] == 178.0
    assert result["high_price"] == 178.0    
    assert result["low_price"] == 170.0
    assert result["period_return_pct"] == round((178.0 - 170.0) / 170.0 * 100, 2)
    
async def test_period_return_pct_positive(mock_cache_manager):
    from investorai_mcp.tools.get_price_history import get_price_history
    
    manager, _ = mock_cache_manager
    mock_session = AsyncMock()
    
    mock_session.__aenter__ = AsyncMock(return_value = mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    
    with patch("investorai_mcp.tools.get_price_history.AsyncSessionLocal",
                return_value=mock_session), \
            patch("investorai_mcp.tools.get_price_history.CacheManager",
                        return_value=manager):
            result = await get_price_history("AAPL")

    assert result["period_return_pct"] > 0

async def test_stale_data_flag_propogated(mock_cache_manager):
    from investorai_mcp.tools.get_price_history import get_price_history
    
    manager, rows = mock_cache_manager
    manager.get_prices = AsyncMock(
        return_value=make_cache_result(rows, is_stale=True, age_hours=25.0)
    )
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value = mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    
    with patch("investorai_mcp.tools.get_price_history.AsyncSessionLocal",
                return_value=mock_session), \
            patch("investorai_mcp.tools.get_price_history.CacheManager",
                        return_value=manager):
            result = await get_price_history("AAPL")
    
    assert result["is_stale"] is True
    assert result["data_age_hours"] == 25.0
    

async def test_empty_data_returns_error(mock_cache_manager):
    from investorai_mcp.tools.get_price_history import get_price_history
    
    manager, _ = mock_cache_manager
    manager.get_prices = AsyncMock(return_value=make_cache_result([], is_stale=True))
    
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value = mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    
    with patch("investorai_mcp.tools.get_price_history.AsyncSessionLocal",
                return_value=mock_session), \
            patch("investorai_mcp.tools.get_price_history.CacheManager",
                        return_value=manager):
            result = await get_price_history("AAPL")
    assert result["error"] is True
    assert result["code"] == "DATA_UNAVAILABLE"
    
async def test_symbol_normalised_to_uppercase():
    from investorai_mcp.tools.get_price_history import get_price_history
    
    result = await get_price_history("fakecrop")
    assert result["error"] is True
    
async def test_price_type_avg_price_used(mock_cache_manager):
    from investorai_mcp.tools.get_price_history import get_price_history
    
    manager, _ = mock_cache_manager
    mock_session = AsyncMock()
    
    mock_session.__aenter__ = AsyncMock(return_value = mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    
    with patch("investorai_mcp.tools.get_price_history.AsyncSessionLocal",
                return_value=mock_session), \
            patch("investorai_mcp.tools.get_price_history.CacheManager",
                        return_value=manager):
                
            result = await get_price_history("AAPL", price_type="avg_price")
    
    #price field should reflect avg_price not adj_close
    assert result["prices"][0]["price"] == result["prices"][0]["avg_price"] 
    
async def test_date_format_is_iso(mock_cache_manager):
    from investorai_mcp.tools.get_price_history import get_price_history
    
    manager, _ = mock_cache_manager
    mock_session = AsyncMock()
    
    mock_session.__aenter__ = AsyncMock(return_value = mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    
    with patch("investorai_mcp.tools.get_price_history.AsyncSessionLocal",
                return_value=mock_session), \
            patch("investorai_mcp.tools.get_price_history.CacheManager",
                        return_value=manager):
            result = await get_price_history("AAPL")
    
    #ISO format : YYYY-MM-DD
    d = result["prices"][0]["date"]
    assert len(d) == 10
    assert d[4] == "-"
    assert d[7] == "-"