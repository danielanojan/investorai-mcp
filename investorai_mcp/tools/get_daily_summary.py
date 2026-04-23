import builtins
import statistics
from typing import Literal

from fastmcp import Context

from investorai_mcp.data.yfinance_adapter import YFinanceAdapter
from investorai_mcp.db import AsyncSessionLocal
from investorai_mcp.db.cache_manager import CacheManager
from investorai_mcp.server import mcp
from investorai_mcp.stocks import is_supported

_adapter: YFinanceAdapter | None = None


def _get_adapter() -> YFinanceAdapter:
    global _adapter
    if _adapter is None:
        _adapter = YFinanceAdapter()
    return _adapter


@mcp.tool()
async def get_daily_summary(
    ticker_symbol: str,
    range: Literal["1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"] = "1Y",
    ctx: Context | None = None,
) -> dict:
    """
    Return a pre-computed statistical summary of a supported stock.

    Computes key metrics from daily price history: Period return,
    high, low, avg_price, volatality and volume.
    It sdoes not use an LLM. Numbers are obtained from the DB


    Use this summary statistics to answer questions like:
    - How has AAPL performed in the last year?
    - What is TSLA's 52-week high and low?
    - What is the average price of NVDA over the last 6 months?


    Do not call for tickers outside the 50-stock universe.
    Use search_ticker first if unsure whether a ticker is supported.

    Args:
        ticker_symbol: Stock ticker symbol, e.g. "AAPL"
        range: Date range for the summary - 1W, 1M, 3M, 6M, 1Y, 3Y, 5Y - default is 1Y.
    Returns:
        Dict with statistical summary and data freshness info
    """
    symbol = ticker_symbol.strip().upper()

    if not is_supported(symbol):
        return {
            "error": True,
            "code": "TICKER_NOT_SUPPORTED",
            "message": f"{symbol} is not in the supported universe of 50 stocks. ",
            "hint": "Use search_ticker tool to find supported tickers.",
        }

    async with AsyncSessionLocal() as session:
        manager = CacheManager(session, _get_adapter())
        await manager.ensure_ticker_exists(symbol)
        result = await manager.get_prices(symbol, range)

    if not result.data:
        return {
            "error": True,
            "code": "DATA_UNAVAILABLE",
            "message": f"No price data available for {symbol}",
            "hint": "Try again in few seconds - a background fetch is in progress.",
        }

    rows = result.data
    adj_closes = [row.adj_close for row in rows]
    volumes = [row.volume for row in rows]

    # period return
    start_price = adj_closes[0]
    end_price = adj_closes[-1]

    period_return_pct = (
        round((end_price - start_price) / start_price * 100, 2) if start_price > 0 else 0
    )

    # high / low
    high_price = max(adj_closes)
    low_price = min(adj_closes)
    high_date = rows[adj_closes.index(high_price)].date
    low_date = rows[adj_closes.index(low_price)].date

    # averages
    avg_price = round(statistics.mean(adj_closes), 2)
    avg_volume = round(statistics.mean(volumes))

    # volatality - annualized stadard deviation of daily returns

    # volatility_pct — annualised standard deviation of daily returns.
    # Measures how much the price jumps around day to day.
    # A stock with 15% volatility moves about 15% per year in either direction
    # on average. Higher = riskier. We multiply by √252 because there are
    # 252 trading days in a year — this converts daily volatility to annual.
    volatality_pct = 0.0
    if len(adj_closes) >= 2:
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
        "low_price": low_price,
        "low_date": low_date,
        "avg_price": avg_price,
        "avg_daily_volume": avg_volume,
        "volatality_pct": volatality_pct,
        "trading_days": len(rows),
        "is_stale": result.is_stale,
        "data_age_hours": round(result.data_age_hours, 2),
    }
