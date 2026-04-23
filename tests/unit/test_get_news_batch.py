from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from investorai_mcp.db.models import NewsArticle


@pytest.fixture(autouse=True)
def register_tools():
    from investorai_mcp.server import _register_tools

    _register_tools()


def make_article(symbol: str, headline: str = "Test headline") -> NewsArticle:
    row = MagicMock(spec=NewsArticle)
    row.symbol = symbol
    row.headline = headline
    row.source = "Reuters"
    row.url = "https://example.com"
    row.published_at = datetime(2026, 4, 1, tzinfo=UTC)
    row.ai_summary = None
    row.sentiment_score = None
    return row


def patch_manager(grouped: dict, needs_refresh: list | None = None):
    mock_manager = MagicMock()
    mock_manager.ensure_ticker_exists = AsyncMock(return_value=MagicMock())
    mock_manager.get_stale_or_missing = AsyncMock(return_value=needs_refresh or [])
    mock_manager.get_news_multi = AsyncMock(return_value=grouped)

    MockCacheManager = MagicMock()
    MockCacheManager.return_value = mock_manager
    MockCacheManager.refresh_news_standalone = AsyncMock()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    return (
        patch(
            "investorai_mcp.tools.get_news_batch.AsyncSessionLocal",
            return_value=mock_session,
        ),
        patch(
            "investorai_mcp.tools.get_news_batch.CacheManager",
            MockCacheManager,
        ),
        MockCacheManager,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


async def test_empty_symbols_returns_empty():
    from investorai_mcp.tools.get_news_batch import get_news_batch

    result = await get_news_batch([])
    assert result["returned"] == 0
    assert result["results"] == {}


async def test_unsupported_ticker_returns_error():
    from investorai_mcp.tools.get_news_batch import get_news_batch

    result = await get_news_batch(["FAKECORP"])
    assert result["error"] is True
    assert result["code"] == "TICKER_NOT_SUPPORTED"


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


async def test_batch_returns_results_for_all_symbols():
    from investorai_mcp.tools.get_news_batch import get_news_batch

    grouped = {
        "AAPL": [make_article("AAPL", "Apple beats earnings")],
        "MSFT": [make_article("MSFT", "Microsoft cloud grows")],
    }
    p1, p2, _ = patch_manager(grouped)
    with p1, p2:
        result = await get_news_batch(["AAPL", "MSFT"])

    assert result["returned"] == 2
    assert result["missing"] == []
    assert "AAPL" in result["results"]
    assert "MSFT" in result["results"]


async def test_stale_news_triggers_refresh():
    from investorai_mcp.tools.get_news_batch import get_news_batch

    grouped = {
        "AAPL": [make_article("AAPL")],
    }
    p1, p2, MockCacheManager = patch_manager(grouped, needs_refresh=["MSFT"])
    with p1, p2:
        await get_news_batch(["AAPL", "MSFT"])

    MockCacheManager.refresh_news_standalone.assert_called_once()


async def test_fresh_news_skips_refresh():
    from investorai_mcp.tools.get_news_batch import get_news_batch

    grouped = {
        "AAPL": [make_article("AAPL")],
    }
    p1, p2, MockCacheManager = patch_manager(grouped, needs_refresh=[])
    with p1, p2:
        await get_news_batch(["AAPL"])

    MockCacheManager.refresh_news_standalone.assert_not_called()


async def test_missing_after_refresh_reported():
    from investorai_mcp.tools.get_news_batch import get_news_batch

    grouped = {
        "AAPL": [make_article("AAPL")],
    }
    p1, p2, _ = patch_manager(grouped, needs_refresh=["MSFT"])
    with p1, p2:
        result = await get_news_batch(["AAPL", "MSFT"])

    assert "AAPL" in result["results"]
    assert "MSFT" in result["missing"]


async def test_result_has_required_fields():
    from investorai_mcp.tools.get_news_batch import get_news_batch

    grouped = {
        "AAPL": [make_article("AAPL", "Apple headline")],
    }
    p1, p2, _ = patch_manager(grouped)
    with p1, p2:
        result = await get_news_batch(["AAPL"])

    r = result["results"]["AAPL"]
    assert "articles" in r
    assert "total" in r
    assert r["total"] == 1
    article = r["articles"][0]
    for field in ("headline", "source", "url", "published_at"):
        assert field in article, f"missing field: {field}"


async def test_multiple_articles_per_symbol():
    from investorai_mcp.tools.get_news_batch import get_news_batch

    grouped = {
        "AAPL": [make_article("AAPL", f"Headline {i}") for i in range(5)],
    }
    p1, p2, _ = patch_manager(grouped)
    with p1, p2:
        result = await get_news_batch(["AAPL"])

    assert result["results"]["AAPL"]["total"] == 5
