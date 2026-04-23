import asyncio
import logging

from investorai_mcp.data.yfinance_adapter import YFinanceAdapter
from investorai_mcp.db import AsyncSessionLocal
from investorai_mcp.db.cache_manager import CacheManager
from investorai_mcp.server import mcp
from investorai_mcp.stocks import is_supported

logger = logging.getLogger(__name__)

_MAX_SYMBOLS = 50

_adapter: YFinanceAdapter | None = None


def _get_adapter() -> YFinanceAdapter:
    global _adapter
    if _adapter is None:
        _adapter = YFinanceAdapter()
    return _adapter


@mcp.tool()
async def get_news_batch(
    symbols: list[str],
    limit: int = 10,
) -> dict:
    """
    Return recent news headlines for multiple stocks in a single call.

    Use instead of calling get_news N times. Automatically refreshes any
    symbols with missing or stale news before returning. One DB query for all symbols.

    Args:
        symbols: List of uppercase ticker symbols, e.g. ["AAPL", "MSFT", "NVDA"]
        limit: Max articles per symbol. Default: 10, max: 50
    Returns:
        Dict with "results" keyed by symbol. Each entry has "articles" list and "total".
    """
    if not symbols:
        return {"results": {}, "requested": 0, "returned": 0, "missing": []}

    symbols = [s.strip().upper() for s in symbols[:_MAX_SYMBOLS]]
    limit = max(1, min(50, limit))

    unsupported = [s for s in symbols if not is_supported(s)]
    if unsupported:
        return {
            "error": True,
            "code": "TICKER_NOT_SUPPORTED",
            "message": f"Unsupported symbols: {unsupported}",
            "hint": "Use search_ticker to find supported tickers.",
        }

    adapter = _get_adapter()

    # Step 1: ensure ticker rows exist + find stale/missing news in one metadata query
    async with AsyncSessionLocal() as session:
        manager = CacheManager(session, adapter)
        await asyncio.gather(*[manager.ensure_ticker_exists(s) for s in symbols])
        needs_refresh = await manager.get_stale_or_missing(symbols, "news")

    # Step 2: parallel news refresh for all stale/missing symbols
    if needs_refresh:
        logger.info("Batch refreshing news for %d symbols: %s", len(needs_refresh), needs_refresh)
        await asyncio.gather(
            *[CacheManager.refresh_news_standalone(s, adapter) for s in needs_refresh]
        )

    # Step 3: single batch read after refresh
    async with AsyncSessionLocal() as session:
        manager = CacheManager(session, adapter)
        grouped = await manager.get_news_multi(symbols, limit_per_symbol=limit)

    results: dict[str, dict] = {}
    missing: list[str] = []

    for symbol in symbols:
        rows = grouped.get(symbol, [])
        if not rows:
            missing.append(symbol)
            continue

        results[symbol] = {
            "symbol": symbol,
            "articles": [
                {
                    "headline": row.headline,
                    "reference": f"{row.source} — {row.url}",
                    "source": row.source,
                    "url": row.url,
                    "published_at": row.published_at.isoformat(),
                    "ai_summary": row.ai_summary,
                    "sentiment_score": row.sentiment_score,
                }
                for row in rows
            ],
            "total": len(rows),
        }

    return {
        "results": results,
        "requested": len(symbols),
        "returned": len(results),
        "missing": missing,
    }
