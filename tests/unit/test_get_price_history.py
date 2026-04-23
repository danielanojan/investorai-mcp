from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from investorai_mcp.db.cache_manager import CacheResult
from investorai_mcp.db.models import PriceHistory


@pytest.fixture(autouse=True)
def register_tools():
    from investorai_mcp.server import _register_tools

    _register_tools()


def make_price_row(d: date, price: float = 174.0) -> PriceHistory:
    row = MagicMock(spec=PriceHistory)
    row.date = d
    row.adj_close = price
    row.avg_price = round((price * 0.99 + price + price * 0.98 + price) / 4, 4)
    row.close = price
    row.volume = 50_000_000
    return row


def make_cache_result(rows, is_stale=False, age_hours=1.0):
    return CacheResult(
        data=rows,
        is_stale=is_stale,
        data_age_hours=age_hours,
        provider_used="yfinance",
    )


@pytest.fixture
def mock_manager():
    rows = [
        make_price_row(date(2026, 1, 1), price=170.0),
        make_price_row(date(2026, 2, 1), price=174.0),
        make_price_row(date(2026, 3, 1), price=178.0),
    ]
    m = MagicMock()
    m.ensure_ticker_exists = AsyncMock(return_value=MagicMock())
    m.get_stale_or_missing = AsyncMock(return_value=[])
    m.get_prices = AsyncMock(return_value=make_cache_result(rows))
    return m, rows


def patch_manager(manager):
    """Patch AsyncSessionLocal and CacheManager for the two-session tool flow."""
    MockCacheManager = MagicMock()
    MockCacheManager.return_value = manager
    MockCacheManager.refresh_prices_standalone = AsyncMock()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    return (
        patch(
            "investorai_mcp.tools.get_price_history.AsyncSessionLocal", return_value=mock_session
        ),
        patch("investorai_mcp.tools.get_price_history.CacheManager", MockCacheManager),
    )


async def test_unsupported_ticker_returns_error():
    from investorai_mcp.tools.get_price_history import get_price_history

    result = await get_price_history("FAKECROP")
    assert result["error"] is True
    assert result["code"] == "TICKER_NOT_SUPPORTED"


async def test_unsupported_ticker_lowercase():
    from investorai_mcp.tools.get_price_history import get_price_history

    result = await get_price_history("fakecrop")
    assert result["error"] is True


async def test_returns_prices_list(mock_manager):
    from investorai_mcp.tools.get_price_history import get_price_history

    manager, rows = mock_manager
    p1, p2 = patch_manager(manager)
    with p1, p2:
        result = await get_price_history("AAPL", range="1Y")

    assert "prices" in result
    assert len(result["prices"]) == 3
    assert result["total_days"] == 3


async def test_price_fields_present(mock_manager):
    from investorai_mcp.tools.get_price_history import get_price_history

    manager, _ = mock_manager
    p1, p2 = patch_manager(manager)
    with p1, p2:
        result = await get_price_history("AAPL")

    first = result["prices"][0]
    for field in ["date", "price", "adj_close", "avg_price", "volume"]:
        assert field in first, f"Expected field '{field}' not found in price record"


async def test_summary_statistics_computed(mock_manager):
    from investorai_mcp.tools.get_price_history import get_price_history

    manager, _ = mock_manager
    p1, p2 = patch_manager(manager)
    with p1, p2:
        result = await get_price_history("AAPL")

    assert result["start_price"] == 170.0
    assert result["end_price"] == 178.0
    assert result["high_price"] == 178.0
    assert result["low_price"] == 170.0
    assert result["period_return_pct"] == round((178.0 - 170.0) / 170.0 * 100, 2)


async def test_period_return_pct_positive(mock_manager):
    from investorai_mcp.tools.get_price_history import get_price_history

    manager, _ = mock_manager
    p1, p2 = patch_manager(manager)
    with p1, p2:
        result = await get_price_history("AAPL")

    assert result["period_return_pct"] > 0


async def test_stale_triggers_refresh(mock_manager):
    from investorai_mcp.tools.get_price_history import get_price_history

    manager, rows = mock_manager
    manager.get_stale_or_missing = AsyncMock(return_value=["AAPL"])

    MockCacheManager = MagicMock()
    MockCacheManager.return_value = manager
    refresh_mock = AsyncMock()
    MockCacheManager.refresh_prices_standalone = refresh_mock

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "investorai_mcp.tools.get_price_history.AsyncSessionLocal", return_value=mock_session
        ),
        patch("investorai_mcp.tools.get_price_history.CacheManager", MockCacheManager),
    ):
        result = await get_price_history("AAPL")

    refresh_mock.assert_called_once()
    assert len(result["prices"]) == len(rows)


async def test_fresh_data_skips_refresh(mock_manager):
    from investorai_mcp.tools.get_price_history import get_price_history

    manager, _ = mock_manager
    manager.get_stale_or_missing = AsyncMock(return_value=[])

    MockCacheManager = MagicMock()
    MockCacheManager.return_value = manager
    refresh_mock = AsyncMock()
    MockCacheManager.refresh_prices_standalone = refresh_mock

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "investorai_mcp.tools.get_price_history.AsyncSessionLocal", return_value=mock_session
        ),
        patch("investorai_mcp.tools.get_price_history.CacheManager", MockCacheManager),
    ):
        await get_price_history("AAPL")

    refresh_mock.assert_not_called()


async def test_empty_data_returns_graceful_response(mock_manager):
    from investorai_mcp.tools.get_price_history import get_price_history

    manager, _ = mock_manager
    manager.get_prices = AsyncMock(return_value=make_cache_result([], is_stale=True))

    p1, p2 = patch_manager(manager)
    with p1, p2:
        result = await get_price_history("AAPL")

    assert "error" not in result
    assert result["prices"] == []
    assert result["total_days"] == 0
    assert "note" in result


async def test_symbol_normalised_to_uppercase():
    from investorai_mcp.tools.get_price_history import get_price_history

    result = await get_price_history("fakecrop")
    assert result["error"] is True


async def test_price_type_avg_price_used(mock_manager):
    from investorai_mcp.tools.get_price_history import get_price_history

    manager, _ = mock_manager
    p1, p2 = patch_manager(manager)
    with p1, p2:
        result = await get_price_history("AAPL", price_type="avg_price")

    assert result["prices"][0]["price"] == result["prices"][0]["avg_price"]


async def test_date_format_is_iso(mock_manager):
    from investorai_mcp.tools.get_price_history import get_price_history

    manager, _ = mock_manager
    p1, p2 = patch_manager(manager)
    with p1, p2:
        result = await get_price_history("AAPL")

    d = result["prices"][0]["date"]
    assert len(d) == 10
    assert d[4] == "-"
    assert d[7] == "-"
