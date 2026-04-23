from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from investorai_mcp.db.cache_manager import CacheResult
from investorai_mcp.db.models import PriceHistory


@pytest.fixture(autouse=True)
def register_tools():
    from investorai_mcp.server import _register_tools

    _register_tools()


def make_row(d: date, price: float, volume: int = 50_000_000) -> PriceHistory:
    row = MagicMock(spec=PriceHistory)
    row.date = d
    row.adj_close = price
    row.volume = volume
    return row


def make_result(rows, is_stale=False):
    return CacheResult(
        data=rows,
        is_stale=is_stale,
        data_age_hours=1.0,
        provider_used="yfinance",
    )


@pytest.fixture
def mock_manager():
    rows = [
        make_row(date(2026, 1, 1), price=150.0, volume=40_000_000),
        make_row(date(2026, 2, 1), price=160.0, volume=50_000_000),
        make_row(date(2026, 3, 1), price=155.0, volume=45_000_000),
        make_row(date(2026, 3, 15), price=180.0, volume=60_000_000),  # high
        make_row(date(2026, 3, 28), price=170.0, volume=55_000_000),
    ]
    m = MagicMock()
    m.ensure_ticker_exists = AsyncMock(return_value=MagicMock())
    m.get_prices = AsyncMock(return_value=make_result(rows))
    return m, rows


# patch manager only creates an AsyncMock objest. It never calls them.
# so it stays a regular def.
# asyncmock is just a regular python object which pretends to be an async
# when called. Creating it is syncronous. Using inside a rest makes it async.

# async with automatically calls await session.__aeter__() when
# wntering and await session.__aexit__() when exiting.
# if its magicMock instead of AsyncMock - python would try to await a non-awaitable
# object and crash with the  error - MagicMock can't be used with await expression.


def patch_manager(manager):
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return (
        patch(
            "investorai_mcp.tools.get_daily_summary.AsyncSessionLocal", return_value=mock_session
        ),
        patch("investorai_mcp.tools.get_daily_summary.CacheManager", return_value=manager),
    )


async def test_unsupported_ticker_returns_error():
    from investorai_mcp.tools.get_daily_summary import get_daily_summary

    result = await get_daily_summary("FAKECROP")
    assert result["error"] is True
    assert result["code"] == "TICKER_NOT_SUPPORTED"


async def test_returns_all_required_fields(mock_manager):
    from investorai_mcp.tools.get_daily_summary import get_daily_summary

    manager, _ = mock_manager
    p1, p2 = patch_manager(manager)
    with p1, p2:
        result = await get_daily_summary("AAPL")

    for field in [
        "symbol",
        "range",
        "start_date",
        "end_date",
        "start_price",
        "end_price",
        "period_return_pct",
        "high_price",
        "high_date",
        "low_price",
        "low_date",
        "avg_price",
        "avg_daily_volume",
        "volatality_pct",
        "trading_days",
        "is_stale",
        "data_age_hours",
    ]:
        assert field in result, f"Missing field: {field}"


async def test_period_return_calculated_correctly(mock_manager):
    from investorai_mcp.tools.get_daily_summary import get_daily_summary

    manager, rows = mock_manager
    p1, p2 = patch_manager(manager)
    with p1, p2:
        result = await get_daily_summary("AAPL")

    # start=150, end=170 -> (170-150)/150 * 100 = 13.33%
    assert result["start_price"] == 150.0
    assert result["end_price"] == 170.0
    assert result["period_return_pct"] == round((170.0 - 150.0) / 150.0 * 100, 2)


async def test_high_and_low_correct(mock_manager):
    from investorai_mcp.tools.get_daily_summary import get_daily_summary

    manager, _ = mock_manager
    p1, p2 = patch_manager(manager)
    with p1, p2:
        result = await get_daily_summary("AAPL")

    assert result["high_price"] == 180.0
    assert result["high_date"] == date(2026, 3, 15)
    assert result["low_price"] == 150.0
    assert result["low_date"] == date(2026, 1, 1)


async def test_trading_days_count(mock_manager):
    from investorai_mcp.tools.get_daily_summary import get_daily_summary

    manager, rows = mock_manager
    p1, p2 = patch_manager(manager)
    with p1, p2:
        result = await get_daily_summary("AAPL")

    assert result["trading_days"] == len(rows)


async def test_empty_data_returns_error(mock_manager):
    from investorai_mcp.tools.get_daily_summary import get_daily_summary

    manager, _ = mock_manager
    manager.get_prices = AsyncMock(return_value=make_result([]))

    p1, p2 = patch_manager(manager)
    with p1, p2:
        result = await get_daily_summary("AAPL")

    assert result["error"] is True
    assert result["code"] == "DATA_UNAVAILABLE"


async def test_stale_data_flag_propogated(mock_manager):
    from investorai_mcp.tools.get_daily_summary import get_daily_summary

    manager, rows = mock_manager
    manager.get_prices = AsyncMock(return_value=make_result(rows, is_stale=True))

    p1, p2 = patch_manager(manager)
    with p1, p2:
        result = await get_daily_summary("AAPL")

    assert result["is_stale"] is True


async def test_volatality_is_non_negative(mock_manager):
    from investorai_mcp.tools.get_daily_summary import get_daily_summary

    manager, _ = mock_manager

    p1, p2 = patch_manager(manager)
    with p1, p2:
        result = await get_daily_summary("AAPL")

    assert result["volatality_pct"] >= 0.0
