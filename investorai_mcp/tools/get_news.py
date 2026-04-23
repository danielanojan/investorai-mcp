import logging
from datetime import UTC, datetime

from fastmcp import Context
from sqlalchemy import select

from investorai_mcp.data.yfinance_adapter import YFinanceAdapter
from investorai_mcp.db import AsyncSessionLocal

logger = logging.getLogger(__name__)
from investorai_mcp.db.cache_manager import TTL_SECONDS, CacheManager
from investorai_mcp.db.models import CacheMetadata, NewsArticle
from investorai_mcp.llm.litellm_client import lf_span
from investorai_mcp.server import mcp
from investorai_mcp.stocks import is_supported

_adapter: YFinanceAdapter | None = None


def _get_adapter() -> YFinanceAdapter:
    global _adapter
    if _adapter is None:
        _adapter = YFinanceAdapter()
    return _adapter


async def _fetch_and_store_news(symbol: str, session) -> list[NewsArticle]:
    """Fetch news from yfinance and write to DB. Returns stored news"""
    from sqlalchemy import delete

    records = await _get_adapter().fetch_news(symbol, limit=50)
    if not records:
        return []

    valid_records = [
        r for r in records if r.headline.strip() and r.source.strip() and r.url.strip()
    ]
    if not valid_records:
        return []

    # Replace all existing news for this symbol so stale/blank rows don't linger.
    await session.execute(delete(NewsArticle).where(NewsArticle.symbol == symbol))

    now = datetime.now(UTC)
    for record in valid_records:
        session.add(
            NewsArticle(
                symbol=symbol,
                headline=record.headline,
                source=record.source,
                url=record.url,
                published_at=record.published_at,
                fetched_at=now,
            )
        )

    await session.commit()

    # Return freshly stored news.
    stmt = (
        select(NewsArticle)
        .where(NewsArticle.symbol == symbol)
        .order_by(NewsArticle.published_at.desc())
        .limit(50)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    result.close()
    return rows


@mcp.tool()
async def get_news(
    ticker_symbol: str,
    limit: int = 10,
    ctx: Context | None = None,
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
            "error": True,
            "code": "TICKER_NOT_SUPPORTED",
            "message": f"{symbol} is not in the supported universe of 50 stocks. ",
            "hint": "Use search_ticker tool to find supported tickers.",
        }

    with lf_span("get_news", input={"symbol": symbol, "limit": limit}):
        async with AsyncSessionLocal() as session:
            manager = CacheManager(session, _get_adapter())
            await manager.ensure_ticker_exists(symbol)

            # check if we have cached news and whether its fresh.
            meta_stmt = select(CacheMetadata).where(
                CacheMetadata.symbol == symbol, CacheMetadata.data_type == "news"
            )
            meta_result = await session.execute(meta_stmt)
            meta = meta_result.scalar_one_or_none()
            meta_result.close()

            ttl_hours = TTL_SECONDS["news"] / 3600
            age_hours = CacheManager._age_hours(meta.last_fetched if meta else None)

            is_stale = meta is None or meta.is_stale or age_hours >= ttl_hours

            if is_stale:
                try:
                    rows = await _fetch_and_store_news(symbol, session)
                    cache_meta = await manager._get_or_create_meta(symbol, "news")
                    await manager._update_meta_success(cache_meta, provider="yfinance")
                except Exception as e:
                    logger.warning("News fetch failed for %s, falling back to cache: %s", symbol, e)
                    stmt = (
                        select(NewsArticle)
                        .where(NewsArticle.symbol == symbol)
                        .order_by(NewsArticle.published_at.desc())
                        .limit(limit)
                    )
                    result = await session.execute(stmt)
                    rows = list(result.scalars().all())
                    result.close()
            else:
                # serve from DB
                stmt = (
                    select(NewsArticle)
                    .where(NewsArticle.symbol == symbol)
                    .order_by(NewsArticle.published_at.desc())
                    .limit(limit)
                )
                result = await session.execute(stmt)
                rows = list(result.scalars().all())
                result.close()

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
            "age_hours": round(age_hours, 2) if age_hours != float("inf") else None,
        }
