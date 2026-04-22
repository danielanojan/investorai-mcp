from datetime import datetime, timezone
from fastmcp import Context
from investorai_mcp.db import AsyncSessionLocal
from investorai_mcp.data.yfinance_adapter import YFinanceAdapter
from investorai_mcp.db.cache_manager import CacheManager
from investorai_mcp.server import mcp
from investorai_mcp.stocks import is_supported

_adapter: YFinanceAdapter | None = None

def _get_adapter() -> YFinanceAdapter:
    global _adapter
    if _adapter is None:
        _adapter = YFinanceAdapter()
    return _adapter

# in memory rat elimit - tracks last refresh time per symbol
# resets on server restart 
#TO DO - In Production - should not reset on server restart. 
_last_refresh : dict[str, datetime] = {}
RATE_LIMIT_SECONDS = 300 #5 minutes per ticker refresh limit to avoid hitting yfinance too often.

@mcp.tool()
async def refresh_ticker(
    ticker_symbol: str,
    ctx: Context | None = None, 
) -> dict:
    """
    Force live data refresh for a supported stock ticker. 

    Bypass the cache TTL and fetches fresh price data from data provider 
    immediately. use this when user explicitly asks for most up-to-date data. 
    
    Rate limited to once in every 5 minutes per ticker to prevent excessive
    API calls to the data provider. 
    
    Do not call this speculatively - only when the user has explicitly asked
    for refresh or when get_cache_status shows degraded/stale status and the user
    wants to fix it. 
    
    Args:
        ticker_symbol: Stock ticker symbol in Uppercase, e.g. "AAPL"
    Returns:
        Dict confirming refresh success, record count and new freshness status. 
        Or error dict if rate limited/ unsupported ticker.
    """
    symbol = ticker_symbol.strip().upper()

    if not is_supported(symbol):
        return {
            "error": True,
            "code": "TICKER_NOT_SUPPORTED",
            "message": f"{symbol} is not in the supported universe of 50 stocks.",
            "hint": "Use search_ticker tool to find supported tickers.",
        }

    #rate limit check
    now = datetime.now(timezone.utc)
    last_time = _last_refresh.get(symbol)
    
    if last_time is not None:
        elapsed = (now - last_time).total_seconds()
        if elapsed < RATE_LIMIT_SECONDS:
            wait = int(RATE_LIMIT_SECONDS - elapsed)
            return {
                "error": True,
                "code": "RATE_LIMITED",
                "message": f"Refresh for {symbol} is rate limited. "
                           f"Please wait {wait} seconds before trying again.",
                "retry_after_seconds": wait       
            }
            
    #record refresh attempt before fetch
    _last_refresh[symbol] = now
    
    async with AsyncSessionLocal() as session:
        cache_manager = CacheManager(session, _get_adapter())
        await cache_manager.ensure_ticker_exists(symbol)
        result = await cache_manager.force_refresh_prices(symbol)
    return {
        "symbol": symbol,
        "success": True,
        "records_loaded": len(result.data),
        "is_stale": result.is_stale,
        "provider_used": result.provider_used, 
        "refreshed_at": now.isoformat(),
        "message": f"successfully refreshed {len(result.data)} "
                    f"price records for {symbol}"
    }
    
    
