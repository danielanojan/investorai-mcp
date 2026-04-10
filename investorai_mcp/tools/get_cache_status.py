from fastmcp import Context 
from sqlalchemy import select

from investorai_mcp.db import AsyncSessionLocal
from investorai_mcp.db.cache_manager import CacheManager, TTL_SECONDS
from investorai_mcp.db.models import CacheMetadata
from investorai_mcp.server import mcp
from investorai_mcp.stocks import is_supported


@mcp.tool()
async def get_cache_status(
    ticker_symbol: str,
    ctx: Context | None = None,
) -> dict:
    """
    Return data freshness status for a supported stock ticker.
    
    Shows when each data type (price history, summary stats, news) was last fetched
    whether its stale, and how many fetch errors have occured. Useful for diagnosing
    why a stock might show outdates data
    
    
    Do not call for tickers outside the 50-stock universe.
    
    Args:
        ticker_symbol: Stock ticker symbol in Uppercase, e.g. "AAPL"
        
    Returns:
        Dict with freshness info per data type, or error if unsupported. 
    """
    symbol = ticker_symbol.strip().upper()
    
    if not is_supported(symbol):
        return {
            "error" : True, 
            "code" : "TICKER_NOT_SUPPORTED",
            "message" : f"{symbol} is not in the supported universe of 50 stocks. ",
            "hint" : "Use search_ticker tool to find supported tickers."
        }
    
    async with AsyncSessionLocal() as session:
        stmt = select(CacheMetadata).where(CacheMetadata.symbol == symbol)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        
    
    if not rows:
        return {
            "symbol": symbol,
            "status": "never_fetched",
            "message": f"No cache entries found for {symbol}. Data will be fetched on first request.",
            "entries": []
        }
        
    entries = []
    for row in rows:
        age_hours = CacheManager._age_hours(row.last_fetched)
        ttl_hours = row.ttl_seconds / 3600
        
        entries.append({
            "data_type": row.data_type,
            "is_stale": row.is_stale,
            "last_fetched": row.last_fetched.isoformat() if row.last_fetched else None,
            "age_hours": round(age_hours, 2) if age_hours != float('inf') else None,
            "ttl_hours": ttl_hours, 
            "fetch_count": row.fetch_count,
            "error_count": row.error_count,
            "provider_used": row.provider_used,
        })
        
    any_stale = any(e["is_stale"] for e in entries)
    any_errors = any(e["error_count"] > 0 for e in entries)
    overall = "stale" if any_stale else "fresh"
    if any_errors:
        overall = "degraded"
        
    return {
        "symbol": symbol,
        "status": overall,
        "entries": entries, 
        "ttl_reference": {
            "price_history": f"{TTL_SECONDS['price_history'] / 3600} hours",
            "news": f"{TTL_SECONDS['news'] / 3600} hours",
            "ticker_info": f"{TTL_SECONDS['ticker_info'] / 3600} hours",
        }
    }
        