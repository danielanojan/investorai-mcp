from datetime import date
from typing import Literal

from fastmcp import Context 

from investorai_mcp.db import AsyncSessionLocal
from investorai_mcp.data.yfinance_adapter import YFinanceAdapter
from investorai_mcp.db.cache_manager import CacheManager
from investorai_mcp.db.models import PriceHistory
from investorai_mcp.llm.litellm_client import lf_span
from investorai_mcp.server import mcp
from investorai_mcp.stocks import is_supported 


_adapter: YFinanceAdapter | None = None

def _get_adapter() -> YFinanceAdapter:
    global _adapter
    if _adapter is None:
        _adapter = YFinanceAdapter()
    return _adapter


def _format_price(row: PriceHistory, price_type:str) -> dict:
    price = {
        "adj_close": row.adj_close,
        "close": row.close,
        "avg_price": row.avg_price,   
    }.get(price_type, row.adj_close)
    
    return {
        "date": row.date.isoformat(),
        "price": round(price, 4),
        "adj_close": round(row.adj_close, 4),
        "close": round(row.close, 4),
        "avg_price": round(row.avg_price, 4),
        "volume": row.volume,
    }
    
    
@mcp.tool()
async def get_price_history(
    ticker_symbol: str,
    range: Literal["1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"] = "1Y",
    price_type: Literal["adj_close", "close", "avg_price"] = "adj_close",
    limit: int = 0,
    ctx : Context | None = None,
) -> dict:
    """
    Return daily price history for a supported stock ticker. 
    
    Fetches OHLCV data from local database cache. If data is stale
    a background refresh is triggered automatically. You still get the data 
    immediately, but it may be outdated. 
    
    Use adj_close(default) for all price comparisons and trend analysis. Close price is the raw closing price and may be distorted by corporate actions.
    It is adjusted for stock splits and dividends and is the most accurate
    representaiotn of the investor returns
    
    Only call this for the tickers in the 50 stock MVP universe. 
    Do not call for crypt, ETFs, options or international stocks. 
    Use search_ticker first if unsure whether a ticker is supported. 
    
    Args:
        ticker symbol: Uppercase ticker symbol (e.g. AAPL, MSFT, GOOGL)
        Range: Date range - 1W, 1M, 3M, 6M, 1Y, 3Y, 5Y - defualt is 1Y
        price_type : adj_close(default), avg_price, or close
        
    Returns:
        dict with prices list, staleness info and summary stats.
    """
    
    symbol = ticker_symbol.strip().upper()
    
    if not is_supported(symbol):
        return {
            "error": True,
            "message": f"Ticker '{symbol}' is not supported.",
            "code": "TICKER_NOT_SUPPORTED",
            "hint" : " Use search_ticker tool to find supported tickers."
            
        }

    with lf_span("get_price_history", input={"symbol": symbol, "range": range}):
        async with AsyncSessionLocal() as session:
            manager = CacheManager(session, _get_adapter())

            #ensure ticker row exists in DB
            await manager.ensure_ticker_exists(symbol)

            # Fetch from cache (triggers background refresh if stale)
            result = await manager.get_prices(symbol, range)

        if not result.data:
            return {
                "error": True,
                "code": "DATA_UNAVAILABLE",
                "message": f"No price data available for {symbol}",
                "hint": "Try again in few seconds - a background fetch is in progress."
            }

        all_prices = [_format_price(row, price_type) for row in result.data]
        if limit > 0 and len(all_prices) > limit:
            # Evenly sample across the full range to preserve trend shape
            step = len(all_prices) / limit
            prices = [all_prices[int(i * step)] for i in range(limit)]
        else:
            prices = all_prices

        #compute summary statistics
        price_values = [p["price"] for p in prices]
        start_price = price_values[0] if price_values else 0
        end_price = price_values[-1] if price_values else 0
        period_return_pct = (
            round((end_price - start_price) / start_price * 100, 2)
            if start_price > 0 else 0
        )

        return {
            "symbol": symbol,
            "range": range,
            "price_type": price_type,
            "prices": prices,
            "total_days": len(prices),
            "start_price": round(start_price, 4),
            "end_price": round(end_price, 4),
            "high_price": round(max(price_values), 4) if price_values else None,
            "low_price": round(min(price_values), 4) if price_values else None,
            "period_return_pct": period_return_pct,
            "is_stale": result.is_stale,
            "data_age_hours": round(result.data_age_hours, 2),
            "provider_used": result.provider_used,
        }