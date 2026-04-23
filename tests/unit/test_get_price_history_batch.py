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
    row.close = price
    row.avg_price = price
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
            "investorai_mcp.tools.get_price_history_batch.AsyncSessionLocal",
            return_value=mock_session,
        ),
        patch(
            "investorai_mcp.tools.get_price_history_batch.CacheManager",
            MockCacheManager,
        ),
        MockCacheManager,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


async def test_empty_symbols_returns_empty():
    from investorai_mcp.tools.get_price_history_batch import get_price_history_batch

    result = await get_price_history_batch([])
    assert result["returned"] == 0
    assert result["results"] == {}


async def test_unsupported_ticker_returns_error():
    from investorai_mcp.tools.get_price_history_batch import get_price_history_batch

    result = await get_price_history_batch(["FAKECORP"])
    assert result["error"] is True
    assert result["code"] == "TICKER_NOT_SUPPORTED"


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


async def test_batch_returns_results_for_all_symbols():
    from investorai_mcp.tools.get_price_history_batch import get_price_history_batch

    grouped = {
        "AAPL": [make_row("AAPL", date(2026, 1, i), 150.0 + i) for i in range(1, 4)],
        "MSFT": [make_row("MSFT", date(2026, 1, i), 300.0 + i) for i in range(1, 4)],
    }
    p1, p2, _ = patch_manager(grouped)
    with p1, p2:
        result = await get_price_history_batch(["AAPL", "MSFT"])

    assert result["returned"] == 2
    assert result["missing"] == []
    assert "AAPL" in result["results"]
    assert "MSFT" in result["results"]


async def test_missing_symbol_triggers_refresh():
    from investorai_mcp.tools.get_price_history_batch import get_price_history_batch

    grouped = {
        "AAPL": [make_row("AAPL", date(2026, 1, i), 150.0 + i) for i in range(1, 4)],
    }
    p1, p2, MockCacheManager = patch_manager(grouped, needs_refresh=["MSFT"])
    with p1, p2:
        await get_price_history_batch(["AAPL", "MSFT"])

    MockCacheManager.refresh_prices_standalone.assert_called_once()


async def test_fresh_data_skips_refresh():
    from investorai_mcp.tools.get_price_history_batch import get_price_history_batch

    grouped = {
        "AAPL": [make_row("AAPL", date(2026, 1, i), 150.0 + i) for i in range(1, 4)],
    }
    p1, p2, MockCacheManager = patch_manager(grouped, needs_refresh=[])
    with p1, p2:
        await get_price_history_batch(["AAPL"])

    MockCacheManager.refresh_prices_standalone.assert_not_called()


async def test_still_missing_after_refresh_reported():
    from investorai_mcp.tools.get_price_history_batch import get_price_history_batch

    grouped = {
        "AAPL": [make_row("AAPL", date(2026, 1, i), 150.0 + i) for i in range(1, 4)],
    }
    p1, p2, _ = patch_manager(grouped, needs_refresh=["MSFT"])
    with p1, p2:
        result = await get_price_history_batch(["AAPL", "MSFT"])

    assert "AAPL" in result["results"]
    assert "MSFT" in result["missing"]


async def test_result_has_required_fields():
    from investorai_mcp.tools.get_price_history_batch import get_price_history_batch

    grouped = {
        "AAPL": [make_row("AAPL", date(2026, 1, i), 150.0 + i) for i in range(1, 5)],
    }
    p1, p2, _ = patch_manager(grouped)
    with p1, p2:
        result = await get_price_history_batch(["AAPL"])

    r = result["results"]["AAPL"]
    for field in ("symbol", "range", "price_type", "prices", "total_days", "period_return_pct"):
        assert field in r, f"missing field: {field}"
    assert len(r["prices"]) > 0
    assert "date" in r["prices"][0]
    assert "price" in r["prices"][0]


async def test_limit_samples_prices():
    from investorai_mcp.tools.get_price_history_batch import get_price_history_batch

    grouped = {
        "AAPL": [make_row("AAPL", date(2026, 1, 1), 100.0 + i) for i in range(100)],
    }
    p1, p2, _ = patch_manager(grouped)
    with p1, p2:
        result = await get_price_history_batch(["AAPL"], limit=10)

    assert result["results"]["AAPL"]["total_days"] == 10


async def test_computes_period_return():
    from investorai_mcp.tools.get_price_history_batch import get_price_history_batch

    grouped = {
        "AAPL": [
            make_row("AAPL", date(2026, 1, 1), 100.0),
            make_row("AAPL", date(2026, 6, 1), 200.0),
        ],
    }
    p1, p2, _ = patch_manager(grouped)
    with p1, p2:
        result = await get_price_history_batch(["AAPL"], limit=0)

    assert result["results"]["AAPL"]["period_return_pct"] == 100.0
