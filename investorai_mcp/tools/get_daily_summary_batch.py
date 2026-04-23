import asyncio
import builtins
import logging
import statistics
from typing import Literal

from investorai_mcp.data.yfinance_adapter import YFinanceAdapter
from investorai_mcp.db import AsyncSessionLocal
from investorai_mcp.db.cache_manager import CacheManager
from investorai_mcp.server import mcp
from investorai_mcp.stocks import is_supported

logger = logging.getLogger(__name__)

_MAX_SYMBOLS = 100

_adapter: YFinanceAdapter | None = None


def _get_adapter() -> YFinanceAdapter:
    global _adapter
    if _adapter is None:
        _adapter = YFinanceAdapter()
    return _adapter


def _compute_summary(symbol: str, rows: list, range: str) -> dict:
    adj_closes = [row.adj_close for row in rows]
    volumes = [row.volume for row in rows]

    start_price = adj_closes[0]
    end_price = adj_closes[-1]
    period_return_pct = (
        round((end_price - start_price) / start_price * 100, 2) if start_price > 0 else 0
    )
    high_price = max(adj_closes)
    low_price = min(adj_closes)
    high_date = rows[adj_closes.index(high_price)].date
    low_date = rows[adj_closes.index(low_price)].date
    avg_price = round(statistics.mean(adj_closes), 2)
    avg_volume = round(statistics.mean(volumes))

    volatality_pct = 0.0
    if len(adj_closes) >= 3:
        daily_returns = [
            (adj_closes[i] - adj_closes[i - 1]) / adj_closes[i - 1]
            for i in builtins.range(1, len(adj_closes))
        ]
        volatality_pct = round(statistics.stdev(daily_returns) * (252**0.5) * 100, 2)

    return {
        "symbol": symbol,
        "range": range,
        "start_date": rows[0].date,
        "end_date": rows[-1].date,
        "start_price": round(start_price, 4),
        "end_price": round(end_price, 4),
        "period_return_pct": period_return_pct,
        "high_price": round(high_price, 4),
        "high_date": high_date,
        "low_price": round(low_price, 4),
        "low_date": low_date,
        "avg_price": avg_price,
        "avg_daily_volume": avg_volume,
        "volatality_pct": volatality_pct,
        "trading_days": len(rows),
    }


@mcp.tool()
async def get_daily_summary_batch(
    symbols: list[str],
    range: Literal["1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"] = "1Y",
) -> dict:
    """
    Return performance statistics for multiple stocks in a single call.

    Use instead of calling get_daily_summary N times for broad comparisons,
    sector queries, or rankings across many tickers. Automatically refreshes
    any symbols with missing or stale data before returning.

    Args:
        symbols: List of uppercase ticker symbols, e.g. ["AAPL", "MSFT", "NVDA"]
        range: Time range for statistics. Default: "1Y"
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
        results[symbol] = _compute_summary(symbol, rows, range)

    return {
        "results": results,
        "range": range,
        "requested": len(symbols),
        "returned": len(results),
        "missing": missing,
    }
