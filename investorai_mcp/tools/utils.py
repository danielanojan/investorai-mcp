"""
Shared data transfer objects for the tools layer.

These dataclasses are used to pass data between delegated MCP tool calls
(get_price_history, get_news, get_stock_info) and the consuming tools
(get_trend_summary), giving proper type safety instead of anonymous dicts.
"""
from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class PriceRow:
    """Single day of price data, mirroring the PriceHistory DB model fields used by tools."""
    date: date
    adj_close: float
    close: float
    avg_price: float
    volume: int


@dataclass
class NewsRow:
    """Single news article, mirroring the NewsArticle DB model fields used by tools."""
    headline: str
    source: str
    url: str
    published_at: datetime
    ai_summary: str | None = None
    sentiment_score: float | None = None


@dataclass
class PriceCacheResult:
    """Wraps a list of PriceRow objects with cache metadata."""
    data: list[PriceRow]
    is_stale: bool
    data_age_hours: float


def price_rows_from_result(result: dict) -> list[PriceRow]:
    """Convert a get_price_history() dict response into a list of PriceRow objects."""
    return [
        PriceRow(
            date=date.fromisoformat(p["date"]),
            adj_close=p["adj_close"],
            close=p["close"],
            avg_price=p["avg_price"],
            volume=p["volume"],
        )
        for p in result.get("prices", [])
    ]


def cache_result_from_price(result: dict) -> PriceCacheResult:
    """Convert a get_price_history() dict response into a PriceCacheResult."""
    return PriceCacheResult(
        data=price_rows_from_result(result),
        is_stale=result["is_stale"],
        data_age_hours=result["data_age_hours"],
    )


def news_rows_from_result(result: dict) -> list[NewsRow]:
    """Convert a get_news() dict response into a list of NewsRow objects."""
    if result.get("error"):
        return []
    return [
        NewsRow(
            headline=a["headline"],
            source=a["source"],
            url=a["url"],
            published_at=datetime.fromisoformat(a["published_at"]),
            ai_summary=a.get("ai_summary"),
            sentiment_score=a.get("sentiment_score"),
        )
        for a in result.get("articles", [])
    ]
