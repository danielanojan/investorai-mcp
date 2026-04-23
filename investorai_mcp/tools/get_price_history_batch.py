import asyncio
import logging
from typing import Literal

from investorai_mcp.data.yfinance_adapter import YFinanceAdapter
from investorai_mcp.db import AsyncSessionLocal
from investorai_mcp.db.cache_manager import CacheManager
from investorai_mcp.db.models import PriceHistory
from investorai_mcp.server import mcp
from investorai_mcp.stocks import is_supported

logger = logging.getLogger(__name__)

_MAX_SYMBOLS = 50
_DEFAULT_LIMIT = 52

_adapter: YFinanceAdapter | None = None


def _get_adapter() -> YFinanceAdapter:
    global _adapter
    if _adapter is None:
        _adapter = YFinanceAdapter()
    return _adapter


def _format_price(row: PriceHistory, price_type: str) -> dict:
    price = {
        "adj_close": row.adj_close,
        "close": row.close,
        "avg_price": row.avg_price,
    }.get(price_type, row.adj_close)

    return {
        "date": row.date.isoformat(),
        "price": round(price, 4),
        "volume": row.volume,
    }


def _sample(prices: list[dict], limit: int) -> list[dict]:
    if limit <= 0 or len(prices) <= limit:
        return prices
    step = len(prices) / limit
    return [prices[int(i * step)] for i in range(limit)]


@mcp.tool()
async def get_price_history_batch(
    symbols: list[str],
    range: Literal["1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"] = "1Y",
    price_type: Literal["adj_close", "close", "avg_price"] = "adj_close",
    limit: int = _DEFAULT_LIMIT,
) -> dict:
    """
    Return daily price history for multiple stocks in a single call.

    Use instead of calling get_price_history N times. Automatically refreshes
    any symbols with missing or stale data before returning.
    Always set limit <= 52 to keep response size manageable for LLM context.

    Args:
        symbols: List of uppercase ticker symbols, e.g. ["AAPL", "MSFT"]
        range: Time range. Default: "1Y"
        price_type: Price field to return. Default: "adj_close"
        limit: Max price points per symbol, evenly sampled. Default: 52
    Returns:
        Dict with "results" keyed by symbol. Empty entries indicate provider returned no data.
    """
    if not symbols:
        return {"results": {}, "range": range, "requested": 0, "returned": 0, "missing": []}

    symbols = [s.strip().upper() for s in symbols[:_MAX_SYMBOLS]]

    unsupported = [s for s in symbols if not is_supported(s)]
    if unsupported:
        return {
            "error": True,
            "code": "TICKER_NOT_SUPPORTED",
            "message": f"Unsupported symbols: {unsupported}",
            "hint": "Use search_ticker to find supported tickers.",
        }

    adapter = _get_adapter()

    # Step 1: ensure ticker rows exist + find stale/missing in one metadata query
    async with AsyncSessionLocal() as session:
        manager = CacheManager(session, adapter)
        await asyncio.gather(*[manager.ensure_ticker_exists(s) for s in symbols])
        needs_refresh = await manager.get_stale_or_missing(symbols, "price_history")

    # Step 2: parallel refresh for all stale/missing symbols
    if needs_refresh:
        logger.info("Batch refreshing %d symbols: %s", len(needs_refresh), needs_refresh)
        await asyncio.gather(
            *[CacheManager.refresh_prices_standalone(s, adapter) for s in needs_refresh]
        )

    # Step 3: single batch read after refresh
    async with AsyncSessionLocal() as session:
        manager = CacheManager(session, adapter)
        grouped = await manager.get_prices_multi(symbols, range)

    results: dict[str, dict] = {}
    missing: list[str] = []

    for symbol in symbols:
        rows = grouped.get(symbol, [])
        if not rows:
            missing.append(symbol)
            continue

        prices = _sample([_format_price(r, price_type) for r in rows], limit)
        price_values = [p["price"] for p in prices]
        start_price = price_values[0]
        end_price = price_values[-1]
        period_return_pct = (
            round((end_price - start_price) / start_price * 100, 2) if start_price > 0 else 0
        )

        results[symbol] = {
            "symbol": symbol,
            "range": range,
            "price_type": price_type,
            "prices": prices,
            "total_days": len(prices),
            "start_price": round(start_price, 4),
            "end_price": round(end_price, 4),
            "period_return_pct": period_return_pct,
        }

    return {
        "results": results,
        "range": range,
        "requested": len(symbols),
        "returned": len(results),
        "missing": missing,
    }
