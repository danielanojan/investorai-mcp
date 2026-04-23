from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from investorai_mcp.db.models import PriceHistory


@pytest.fixture(autouse=True)
def register_tools():
    from investorai_mcp.server import _register_tools

    _register_tools()


def make_row(symbol: str, d: date, price: float, volume: int = 50_000_000) -> PriceHistory:
    row = MagicMock(spec=PriceHistory)
    row.symbol = symbol
    row.date = d
    row.adj_close = price
    row.volume = volume
    return row


def patch_manager(grouped: dict, needs_refresh: list | None = None):
    mock_manager = MagicMock()
    mock_manager.ensure_ticker_exists = AsyncMock(return_value=MagicMock())
    mock_manager.get_stale_or_missing = AsyncMock(return_value=needs_refresh or [])
    mock_manager.get_prices_multi = AsyncMock(return_value=grouped)

    MockCacheManager = MagicMock()
    MockCacheManager.return_value = mock_manager
    MockCacheManager.refresh_prices_standalone = AsyncMock()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    return (
        patch(
            "investorai_mcp.tools.get_daily_summary_batch.AsyncSessionLocal",
            return_value=mock_session,
        ),
        patch(
            "investorai_mcp.tools.get_daily_summary_batch.CacheManager",
            MockCacheManager,
        ),
        MockCacheManager,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


async def test_empty_symbols_returns_empty():
    from investorai_mcp.tools.get_daily_summary_batch import get_daily_summary_batch

    result = await get_daily_summary_batch([])
    assert result["returned"] == 0
    assert result["results"] == {}


async def test_unsupported_ticker_returns_error():
    from investorai_mcp.tools.get_daily_summary_batch import get_daily_summary_batch

    result = await get_daily_summary_batch(["FAKECORP", "AAPL"])
    assert result["error"] is True
    assert result["code"] == "TICKER_NOT_SUPPORTED"


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


async def test_batch_returns_results_for_all_symbols():
    from investorai_mcp.tools.get_daily_summary_batch import get_daily_summary_batch

    grouped = {
        "AAPL": [
            make_row("AAPL", date(2026, 1, 1), 150.0),
            make_row("AAPL", date(2026, 3, 1), 160.0),
            make_row("AAPL", date(2026, 6, 1), 180.0),
        ],
        "MSFT": [
            make_row("MSFT", date(2026, 1, 1), 300.0),
            make_row("MSFT", date(2026, 3, 1), 330.0),
            make_row("MSFT", date(2026, 6, 1), 360.0),
        ],
    }
    p1, p2, _ = patch_manager(grouped)
    with p1, p2:
        result = await get_daily_summary_batch(["AAPL", "MSFT"])

    assert result["returned"] == 2
    assert result["missing"] == []
    assert "AAPL" in result["results"]
    assert "MSFT" in result["results"]


async def test_batch_computes_correct_return_pct():
    from investorai_mcp.tools.get_daily_summary_batch import get_daily_summary_batch

    grouped = {
        "AAPL": [
            make_row("AAPL", date(2026, 1, 1), 100.0),
            make_row("AAPL", date(2026, 3, 1), 120.0),
            make_row("AAPL", date(2026, 6, 1), 150.0),
        ],
    }
    p1, p2, _ = patch_manager(grouped)
    with p1, p2:
        result = await get_daily_summary_batch(["AAPL"])

    assert result["results"]["AAPL"]["period_return_pct"] == 50.0


async def test_batch_missing_symbol_triggers_refresh():
    from investorai_mcp.tools.get_daily_summary_batch import get_daily_summary_batch

    grouped = {
        "AAPL": [
            make_row("AAPL", date(2026, 1, 1), 150.0),
            make_row("AAPL", date(2026, 3, 1), 160.0),
            make_row("AAPL", date(2026, 6, 1), 170.0),
        ],
    }
    # MSFT is stale/missing
    p1, p2, MockCacheManager = patch_manager(grouped, needs_refresh=["MSFT"])
    with p1, p2:
        await get_daily_summary_batch(["AAPL", "MSFT"])

    MockCacheManager.refresh_prices_standalone.assert_called_once()


async def test_batch_no_refresh_when_all_fresh():
    from investorai_mcp.tools.get_daily_summary_batch import get_daily_summary_batch

    grouped = {
        "AAPL": [
            make_row("AAPL", date(2026, 1, 1), 150.0),
            make_row("AAPL", date(2026, 3, 1), 160.0),
            make_row("AAPL", date(2026, 6, 1), 170.0),
        ],
    }
    p1, p2, MockCacheManager = patch_manager(grouped, needs_refresh=[])
    with p1, p2:
        await get_daily_summary_batch(["AAPL"])

    MockCacheManager.refresh_prices_standalone.assert_not_called()


async def test_batch_still_missing_after_refresh_reported():
    from investorai_mcp.tools.get_daily_summary_batch import get_daily_summary_batch

    # MSFT needs refresh but provider returns nothing — stays missing
    grouped = {
        "AAPL": [
            make_row("AAPL", date(2026, 1, 1), 150.0),
            make_row("AAPL", date(2026, 3, 1), 160.0),
            make_row("AAPL", date(2026, 6, 1), 170.0),
        ],
    }
    p1, p2, _ = patch_manager(grouped, needs_refresh=["MSFT"])
    with p1, p2:
        result = await get_daily_summary_batch(["AAPL", "MSFT"])

    assert "AAPL" in result["results"]
    assert "MSFT" in result["missing"]


async def test_batch_summary_has_required_fields():
    from investorai_mcp.tools.get_daily_summary_batch import get_daily_summary_batch

    grouped = {
        "AAPL": [
            make_row("AAPL", date(2026, 1, 1), 150.0),
            make_row("AAPL", date(2026, 3, 1), 160.0),
            make_row("AAPL", date(2026, 6, 1), 180.0),
        ],
    }
    p1, p2, _ = patch_manager(grouped)
    with p1, p2:
        result = await get_daily_summary_batch(["AAPL"])

    summary = result["results"]["AAPL"]
    for field in (
        "symbol",
        "range",
        "start_price",
        "end_price",
        "period_return_pct",
        "high_price",
        "low_price",
        "avg_price",
        "volatality_pct",
        "trading_days",
    ):
        assert field in summary, f"missing field: {field}"


async def test_batch_range_passed_through():
    from investorai_mcp.tools.get_daily_summary_batch import get_daily_summary_batch

    grouped = {
        "AAPL": [
            make_row("AAPL", date(2026, 1, 1), 150.0),
            make_row("AAPL", date(2026, 3, 1), 160.0),
            make_row("AAPL", date(2026, 6, 1), 170.0),
        ],
    }
    p1, p2, _ = patch_manager(grouped)
    with p1, p2:
        result = await get_daily_summary_batch(["AAPL"], range="3M")

    assert result["range"] == "3M"
    assert result["results"]["AAPL"]["range"] == "3M"
