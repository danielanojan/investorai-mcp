from fastmcp import Context
from sqlalchemy import select

from investorai_mcp.db import AsyncSessionLocal
from investorai_mcp.db.models import Ticker
from investorai_mcp.server import mcp
from investorai_mcp.stocks import is_supported

"""
IN MCP tools - context is only required when 
1. Tools are user specific (portfolio, watchlist, preferences)
2. Tools which depend on session time (current selected stocks))
3. Tools which need auth/ credentials passed through

When you do not need context
1. Pure data fetching tools - where input arguments are sufficient
2. Stateless tools - same input always give same output. 

"""
@mcp.tool()
async def get_stock_info(
    ticker_symbol: str,
    ctx: Context | None= None,
    ) -> dict:
    """Return profile information for a supported stock ticker. 
    
    Returns the company name, sector, exchange, market_cap and currency for the 
    given ticker. Use this before get_price_history to confirm the ticker
    is supported and get its full name. 
    
    Do not call this for tickers not in 50-stock universe - use search_ticker first if unsure. 
    
    Args: 
        ticker_symbol: Stock ticker symbol, e.g. "AAPL"
        
    Returns:
        Company profile dict, or error dict if ticker is not supported. 
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
        ticker = await session.get(Ticker, symbol)
        
        if ticker is None:       # this is DB lookup 
            #if the ticker is none - Static fallback - the ticker is supported but we do not still have in our DB. 
            # this can happen to cold starts. In this case, we return the basic information from stocks.py but notice
            # most other information including market_cap, currency, shares outstanding are None. We return the data source is static. 
            
            from investorai_mcp.stocks import get_ticker_info
            
            info = get_ticker_info(symbol) # this function is used to pull information from static stocks.py file. 
            #its async because in the future we may want to pull from an API instead of static file.
            
            return {
                "symbol": symbol, 
                "name": info["name"],
                "sector": info["sector"],
                "exchange": info["exchange"],
                "market_cap": None, 
                "currency": None,
                "shares_outstanding": None,
                "is_supported": True,
                "data_source": "static",
            }
        # if its in the DB - we return the DB record - this will be a full DB record with market cap, currency and shares outstanding. 
        # We also indicate the data source is database.
        
        return {
            "symbol": ticker.symbol,
            "name": ticker.name,
            "sector": ticker.sector,
            "exchange": ticker.exchange,
            "market_cap": ticker.market_cap,
            "currency": ticker.currency,
            "shares_outstanding": ticker.shares_outstanding,
            "is_supported": True,
            "data_source": "database",
        }