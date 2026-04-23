import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from investorai_mcp.db.models import (
    Base,
    CacheMetadata,
    EvalLog,
    LLMUsageLog,
    PriceHistory,
    Ticker,
)

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def engine():
    eng = create_async_engine(TEST_DB_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s


@pytest.fixture
def sample_ticker():
    return Ticker(
        symbol="AAPL",
        name="Apple Inc.",
        sector="Technology",
        exchange="NASDAQ",
        market_cap=3_000_000_000_000,
        currency="USD",
        is_supported=True,
    )


####### here we are testing the existance fo all 6 tables


async def test_all_six_tables_created(engine):
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    expected = {
        "tickers",
        "price_history",
        "news_articles",
        "cache_metadata",
        "eval_log",
        "llm_usage_log",
    }
    assert expected.issubset(set(tables))

    ############# ticker


async def test_ticker_insert_and_retrieve(session, sample_ticker):
    session.add(sample_ticker)
    await session.commit()

    result = await session.get(Ticker, "AAPL")
    assert result is not None
    assert result.name == "Apple Inc."
    assert result.sector == "Technology"
    assert result.is_supported is True
    assert result.currency == "USD"


async def test_ticker_primary_key_is_symbol(session, sample_ticker):
    session.add(sample_ticker)
    await session.commit()

    result = await session.get(Ticker, "AAPL")
    assert result.symbol == "AAPL"


async def test_ticker_duplicate_symbol_raises(session, sample_ticker):
    from sqlalchemy.exc import IntegrityError

    session.add(sample_ticker)
    await session.commit()

    duplicate = Ticker(
        symbol="AAPL",
        name="Duplicate Apple",
        sector="Technology",
        exchange="NASDAQ",
    )

    session.add(duplicate)
    with pytest.raises(IntegrityError):
        await session.commit()

    # price history


async def test_price_history_insert(session, sample_ticker):
    from datetime import date

    session.add(sample_ticker)
    await session.commit()

    price = PriceHistory(
        symbol="AAPL",
        date=date(2024, 1, 1),
        open=150.0,
        high=155.0,
        low=149.0,
        close=154.0,
        volume=55_000_000,
        adj_close=154.0,
        avg_price=(150.0 + 155.0 + 149.0 + 154.0) / 4,
    )
    session.add(price)
    await session.commit()

    result = await session.get(PriceHistory, price.id)
    assert result.symbol == "AAPL"
    assert result.date == date(2024, 1, 1)
    assert result.open == 150.0
    assert result.split_factor == 1.0


async def test_price_history_unique_symbol_date(session, sample_ticker):
    from datetime import date

    from sqlalchemy.exc import IntegrityError

    session.add(sample_ticker)
    await session.commit()

    def make_price():
        return PriceHistory(
            symbol="AAPL",
            date=date(2026, 3, 28),
            open=172.0,
            high=175.0,
            low=171.0,
            close=174.0,
            volume=1_000_000,
            adj_close=174.0,
            avg_price=173.0,
        )

    session.add(make_price())
    await session.commit()
    session.add(make_price())
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_price_history_cascade_delete(session, sample_ticker):
    from datetime import date

    session.add(sample_ticker)
    await session.commit()

    price = PriceHistory(
        symbol="AAPL",
        date=date(2026, 3, 28),
        open=172.0,
        high=175.0,
        low=171.0,
        close=174.0,
        volume=1_000_000,
        adj_close=174.0,
        avg_price=173.0,
    )
    session.add(price)
    await session.commit()
    price_id = price.id

    await session.delete(sample_ticker)
    await session.commit()

    result = await session.get(PriceHistory, price_id)
    assert result is None


# cache metadata


async def test_cache_metadata_insert(session, sample_ticker):
    session.add(sample_ticker)
    await session.commit()

    cache = CacheMetadata(
        symbol="AAPL",
        data_type="price_history",
        ttl_seconds=86400,
        is_stale=True,
    )

    session.add(cache)
    await session.commit()

    result = await session.get(CacheMetadata, cache.id)
    assert result.symbol == "AAPL"
    assert result.is_stale is True
    assert result.fetch_count == 0
    assert result.error_count == 0


async def test_cache_metadata_unique_symbol_data_type(session, sample_ticker):
    from sqlalchemy.exc import IntegrityError

    session.add(sample_ticker)
    await session.commit()

    session.add(CacheMetadata(symbol="AAPL", data_type="price_history", ttl_seconds=86400))
    await session.commit()

    session.add(CacheMetadata(symbol="AAPL", data_type="price_history", ttl_seconds=86400))
    with pytest.raises(IntegrityError):
        await session.commit()


# WAL mode


async def test_wal_mode_can_be_enabled(engine):
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        result = await conn.exec_driver_sql("PRAGMA journal_mode")
        row = result.fetchone()
    assert row[0] in ("wal", "memory")  # memory for :memory : DB


# evalLog


async def test_eval_log_insert(session, sample_ticker):
    import uuid

    session.add(sample_ticker)
    await session.commit()

    entry = EvalLog(
        query_id=str(uuid.uuid4()),
        symbol="AAPL",
        question="What was AAPL's adjusted close on 2026-03-28?",
        ai_answer="$174.00 [Source: DB • 2026-03-28]",
        ground_truth="174.00",
        pass_fail="PASS",  # noqa: S106
        source="eval_suite",
    )

    session.add(entry)
    await session.commit()

    result = await session.get(EvalLog, entry.id)
    assert result.pass_fail == "PASS"  # noqa: S105
    assert result.source == "eval_suite"


#### LLMUsgaeLogs


async def test_llm_usage_log_insert(session):
    entry = LLMUsageLog(
        session_hash="abc123",
        provider="anthropic",
        model="claude-sonnet-4",
        tool_name="get_trend_summary",
        tokens_in=512,
        tokens_out=128,
        latency_ms=1840,
        status="success",
    )
    session.add(entry)
    await session.commit()

    result = await session.get(LLMUsageLog, entry.id)
    assert result.provider == "anthropic"
    assert result.model == "claude-sonnet-4"
    assert result.tokens_in == 512
    assert result.status == "success"
