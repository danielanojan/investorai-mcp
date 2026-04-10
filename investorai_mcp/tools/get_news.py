from datetime import datetime, timezone
from typing import Literal

from fastmcp import Context
from sqlalchemy import select

from investorai_mcp.db import AsyncSessionLocal
from investorai_mcp.data.yfinance_adapter import YFinanceAdapter
from investorai_mcp.db.cache_manager import CacheManager, TTL_SECONDS
from investorai_mcp.db.models import CacheMetadata, NewsArticle
from investorai_mcp.server import mcp
from investorai_mcp.stocks import is_supported


_adapter = YFinanceAdapter()

async def _fetch_and_store_news(symbol:str, session) -> list[NewsArticle]:
    """Fetch news from yfinance and write to DB. Returns stored news"""
    from investorai_mcp.data.base import NewsRecord
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    
    records = await _adapter.fetch_news(symbol, limit=50)
    if not records:
        return []
    
    for record in records:
        stmt = sqlite_insert(NewsArticle).values(
            symbol=symbol,
            headline=record.headline,
            source=record.source,
            url=record.url,
            published_at=record.published_at,
            fetched_at=datetime.now(timezone.utc),
        ).on_conflict_do_nothing()
        await session.execute(stmt)
        
    await session.commit()
    
    #Return freshly stored news. 
    stmt = (
        select(NewsArticle)
        .where(NewsArticle.symbol == symbol)
        .order_by(NewsArticle.published_at.desc())
        .limit(50)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())

@mcp.tool()
async def get_news(
    ticker_symbol: str,
    limit: int = 10,
    ctx : Context | None = None,
) -> dict:
    """
    Return recent news articles for a supported stock ticker. 
    
    Fetches news from the DB cache. If no cache news exists, fetches
    live from the data provider. Articles include headline, source, url and 
    pblication date
    
    
    Note: AI summaries and sentiment scores are added in a later processing step. 
    They may be null for recently fetched articles. 
    
    Do not call this for tickers outside the 50-stock universe.
    Use search_ticker first if unsure whether a ticker is supported.
    
    Args: 
        ticker_symbol: Stock ticker symbol, e.g. "AAPL"
        limit: Maximum number of articles to return, default is 10. max is 50
        
    Returns:
        Dict with list of news articles (headline, source, url, published_at) and cache freshness info
    """
    symbol = ticker_symbol.strip().upper()
    limit = max(1, min(50, limit))  # ensure limit is between 1 and 50
    
    
    if not is_supported(symbol):
        return {
            "error" : True, 
            "code" : "TICKER_NOT_SUPPORTED",
            "message" : f"{symbol} is not in the supported universe of 50 stocks. ",
            "hint" : "Use search_ticker tool to find supported tickers."
        }
        
    async with AsyncSessionLocal() as session:
        #check if we have cached news and whether its fresh. 
        meta_stmt = select(CacheMetadata).where(
            CacheMetadata.symbol == symbol, 
            CacheMetadata.data_type == "news"
        )
        meta_result = await session.execute(meta_stmt)
        meta = meta_result.scalar_one_or_none()
        
        ttl_hours = TTL_SECONDS["news"] / 3600
        age_hours = CacheManager._age_hours(
            meta.last_fetched if meta else None
        )
        
        is_stale = meta is None or meta.is_stale or age_hours >= ttl_hours
        
        if is_stale:
            #fetch live and store
            rows = await _fetch_and_store_news(symbol, session)
            
            #update cache metadata
            manager = CacheManager(session, _adapter)
            cache_meta = await manager._get_or_create_meta(symbol, "news")
            await manager._update_meta_success(cache_meta, provider="yfinance")
        else:
            #serve from DB

            stmt = (
                select(NewsArticle)
                .where(NewsArticle.symbol == symbol)
                .order_by(NewsArticle.published_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
            
    if not rows:
        return {
            "symbol": symbol, 
            "articles": [],
            "total": 0,
            "message": f"No news articles found for {symbol}.",
            "is_stale": False, 
        }
    
    articles = [
        {
            "headline": row.headline,
            "source": row.source,
            "url": row.url,
            "published_at": row.published_at.isoformat(),
            "ai_summary": row.ai_summary,
            "sentiment_score": row.sentiment_score,
        }
        for row in rows[:limit]
        
    ]
    return {
        "symbol": symbol, 
        "articles": articles,
        "total": len(articles),
        "is_stale": is_stale,
        "age_hours": round(age_hours, 2) if age_hours != float('inf') else None,
    }