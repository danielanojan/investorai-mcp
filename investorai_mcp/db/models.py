from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Ticker(Base):
    __tablename__ = "tickers"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    sector: Mapped[str] = mapped_column(String, nullable=False)
    exchange: Mapped[str] = mapped_column(String, nullable=False)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    shares_outstanding: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="USD")
    is_supported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_updated: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # relationships
    prices: Mapped[list["PriceHistory"]] = relationship(
        back_populates="ticker", cascade="all, delete-orphan"
    )
    news: Mapped[list["NewsArticle"]] = relationship(
        back_populates="ticker", cascade="all, delete-orphan"
    )
    cache_entries: Mapped[list["CacheMetadata"]] = relationship(
        back_populates="ticker", cascade="all, delete-orphan"
    )
    eval_entries: Mapped[list["EvalLog"]] = relationship(back_populates="ticker")

    __table_args__ = (Index("idx_tickers_sector", "sector"),)


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.symbol", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    adj_close: Mapped[float] = mapped_column(Float, nullable=False)
    avg_price: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)
    split_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    ticker: Mapped["Ticker"] = relationship(back_populates="prices")

    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_price_history_symbol_date"),
        Index("idx_ph_symbol_date", "symbol", "date"),
        CheckConstraint("open > 0", name="ck_ph_open_positive"),
        CheckConstraint("adj_close > 0", name="ck_ph_adj_close_positive"),
        CheckConstraint("volume >= 0", name="ck_ph_volume_non_negative"),
        CheckConstraint("close > 0", name="ck_ph_close_positive"),
    )


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.symbol", ondelete="CASCADE"), nullable=False
    )
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    ticker: Mapped["Ticker"] = relationship(back_populates="news")

    __table_args__ = (
        Index("idx_news_symbol_published", "symbol", "published_at"),
        CheckConstraint(
            "sentiment_score BETWEEN -1 AND 1", name="ck_news_sentiment_range"
        ),
    )


class CacheMetadata(Base):
    __tablename__ = "cache_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.symbol", ondelete="CASCADE"), nullable=False
    )
    data_type: Mapped[str] = mapped_column(String, nullable=False)
    last_fetched: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fetch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_used: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    ticker: Mapped["Ticker"] = relationship(back_populates="cache_entries")

    __table_args__ = (
        UniqueConstraint("symbol", "data_type", name="uq_cache_symbol_data_type"),
        CheckConstraint(
            "data_type IN ('price_history', 'news', 'ticker_info', 'sentiment')",
            name="ck_cache_data_type_valid",
        ),
        CheckConstraint("ttl_seconds > 0", name="ck_cache_ttl_positive"),
    )


class EvalLog(Base):
    __tablename__ = "eval_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    symbol: Mapped[str | None] = mapped_column(
        String, ForeignKey("tickers.symbol"), nullable=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    ai_answer: Mapped[str] = mapped_column(Text, nullable=False)
    ground_truth: Mapped[str | None] = mapped_column(Text, nullable=True)
    pass_fail: Mapped[str] = mapped_column(String, nullable=False)
    deviation_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    violation_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="live")
    ts: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    ticker: Mapped["Ticker | None"] = relationship(back_populates="eval_entries")

    __table_args__ = (
        Index("idx_eval_query_id", "query_id"),
        Index("idx_eval_ts", "ts"),
        CheckConstraint(
            "pass_fail IN ('PASS', 'FAIL', 'SKIP')", name="ck_eval_pass_fail_valid"
        ),
        CheckConstraint(
            "source IN ('live', 'eval_suite')", name="ck_eval_source_valid"
        ),
    )


class LLMUsageLog(Base):
    __tablename__ = "llm_usage_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_hash: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String, nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_llm_session", "session_hash"),
        Index("idx_llm_ts", "ts"),
        CheckConstraint("tokens_in >= 0", name="ck_llm_tokens_in_non_negative"),
        CheckConstraint("tokens_out >= 0", name="ck_llm_tokens_out_non_negative"),
        CheckConstraint(
            "status IN ('success', 'error', 'rate_limited', 'timeout')",
            name="ck_llm_status_valid",
        ),
    )
