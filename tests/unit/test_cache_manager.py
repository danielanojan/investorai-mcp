from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from investorai_mcp.data.base import OHLCVRecord
from investorai_mcp.db.cache_manager import TTL_SECONDS, CacheManager, CacheResult
from investorai_mcp.db.models import Base, CacheMetadata, PriceHistory, Ticker

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def engine():
    eng = create_async_engine(TEST_DB_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s


@pytest.fixture
def mock_adapter():
    adapter = MagicMock()
    adapter.fetch_ohlcv = AsyncMock(return_value=[])
    adapter.fetch_news = AsyncMock(return_value=[])
    adapter.fetch_ticker_info = AsyncMock()
    return adapter


@pytest.fixture
async def cache_manager(session, mock_adapter):
    return CacheManager(session, mock_adapter)


@pytest.fixture
async def seeded_ticker(session):
    ticker = Ticker(
        symbol="AAPL",
        name="Apple Inc.",
        exchange="NASDAQ",
        sector="Technology",
    )
    session.add(ticker)
    await session.commit()
    return ticker


def make_ohlcv(symbol="AAPL", trade_date=None, adj_close=174.0):
    return OHLCVRecord(
        symbol=symbol,
        date=trade_date or date(2026, 3, 28),
        open=172.0,
        high=176.0,
        low=170.0,
        close=adj_close,
        adj_close=adj_close,
        volume=50_000_000,
        avg_price=(172.0 + 176.0 + 170.0 + adj_close) / 4,
    )


# TTL constants ---------------------------------
def test_ttl_values_are_reasonable():
    assert TTL_SECONDS["price_history"] == 86400  # 1 day
    assert TTL_SECONDS["news"] == 14400  # 4 hours
    assert TTL_SECONDS["ticker_info"] == 604800  # 7 days


# meta creation ---------------------------------


async def test_get_or_create_meta_creates_on_first_call(cache_manager, seeded_ticker, session):
    meta = await cache_manager._get_or_create_meta("AAPL", "price_history")
    assert meta.symbol == "AAPL"
    assert meta.data_type == "price_history"
    assert meta.is_stale is True
    assert meta.fetch_count == 0
    assert meta.ttl_seconds == 86400


async def test_get_or_create_meta_returns_existing(cache_manager, seeded_ticker, session):
    # Create initial meta
    meta1 = await cache_manager._get_or_create_meta("AAPL", "price_history")
    meta2 = await cache_manager._get_or_create_meta("AAPL", "price_history")
    assert meta1.id == meta2.id


#### Age Calculation ---------------------------------
def test_age_hours_none_returns_infinity():
    age = CacheManager._age_hours(None)
    assert age == float("inf")


def test_age_hours_recent_is_small():
    recent_time = datetime.now(UTC) - timedelta(minutes=30)
    age = CacheManager._age_hours(recent_time)
    assert 0.4 < age < 0.6  # Should be around 0.5 hours


def test_age_hours_old_is_large():
    old_time = datetime.now(UTC) - timedelta(hours=25)
    age = CacheManager._age_hours(old_time)
    assert age > 24  # Should be greater than 24 hours


#### Period to cutoff calculation ---------------------------------
def test_period_to_cutoff_1y():
    from datetime import date, timedelta

    cutoff = CacheManager._period_to_cutoff("1Y")
    expected = date.today() - timedelta(days=365)
    assert abs((cutoff - expected).days) <= 1  # Allow 1 day margin due to month length variations


def test_period_to_cutoff_5y():
    from datetime import date, timedelta

    cutoff = CacheManager._period_to_cutoff("5Y")
    expected = date.today() - timedelta(days=365 * 5)
    assert (
        abs((cutoff - expected).days) <= 1
    )  # Allow 1 day margin due to leap years and month length variations


def test_period_to_cutoff_unknown_defaults_to_1y():
    from datetime import date, timedelta

    cutoff = CacheManager._period_to_cutoff("UNKNOWN")
    expected = date.today() - timedelta(days=365)
    assert abs((cutoff - expected).days) <= 1  # Should default to 1 year cutoff


# get prices - stale path --------------------------------- -
async def test_get_prices_stale_triggers_background_refresh(
    cache_manager, seeded_ticker, mock_adapter
):
    mock_adapter.fetch_ohlcv.return_value = [make_ohlcv()]

    with patch("asyncio.create_task") as mock_create_task:
        result = await cache_manager.get_prices("AAPL", "1Y")
        assert mock_create_task.called, "Expected background refresh task to be created"

    assert isinstance(result, CacheResult)
    assert result.is_stale is True


async def test_get_prices_stale_returns_cached_result(cache_manager, seeded_ticker, mock_adapter):
    result = await cache_manager.get_prices("AAPL", "1Y")
    assert isinstance(result, CacheResult)
    assert isinstance(result.data, list)


### upsert prices --------------------------------- -
async def test_upsert_prices_writes_to_db(cache_manager, seeded_ticker, session):
    records = [
        make_ohlcv(trade_date=date(2026, 3, 26), adj_close=172.0),
        make_ohlcv(trade_date=date(2026, 3, 27), adj_close=174.0),
        make_ohlcv(trade_date=date(2026, 3, 28), adj_close=176.0),
    ]
    await cache_manager._upsert_prices("AAPL", records)

    from sqlalchemy import select

    stmt = select(PriceHistory).where(PriceHistory.symbol == "AAPL")
    result = await session.execute(stmt)
    rows = result.scalars().all()
    assert len(rows) == 3


async def test_upsert_prices_updates_on_conflict(cache_manager, seeded_ticker, session):
    record = make_ohlcv(trade_date=date(2026, 3, 28), adj_close=174.0)
    await cache_manager._upsert_prices("AAPL", [record])

    # upsert again with updated price
    updated = make_ohlcv(trade_date=date(2026, 3, 28), adj_close=180.0)
    await cache_manager._upsert_prices("AAPL", [updated])

    from sqlalchemy import select

    stmt = select(PriceHistory).where(
        PriceHistory.symbol == "AAPL",
        PriceHistory.date == date(2026, 3, 28),
    )
    result = await session.execute(stmt)
    row = result.scalar_one()
    assert row.adj_close == 180.0


# ensure tickket exists --------------------------------- -
async def ensure_ticker_exists_returns_existing(cache_manager, seeded_ticker):
    result = await cache_manager.ensure_ticker_exists("AAPL")
    assert result is not None
    assert result.symbol == "AAPL"


async def test_ensure_ticker_exists_creates_from_stocks_list(cache_manager, session):
    # NVIDIA in stocks.py but not in DB yet
    result = await cache_manager.ensure_ticker_exists("NVDA")
    assert result is not None
    assert result.symbol == "NVDA"
    assert result.sector == "Technology"


async def test_ensure_ticker_exists_unknown_returns_none(cache_manager, session):
    result = await cache_manager.ensure_ticker_exists("FAKEPOP")
    assert result is None


# meta analysis / error updates --------------------------------- -
async def test_update_meta_success_clears_stale(cache_manager, seeded_ticker, session):
    meta = await cache_manager._get_or_create_meta("AAPL", "price_history")
    assert meta.is_stale is True

    await cache_manager._update_meta_success(meta, "yfinance")

    from sqlalchemy import select

    stmt = select(CacheMetadata).where(CacheMetadata.id == meta.id)
    result = await session.execute(stmt)
    updated_meta = result.scalar_one()
    assert updated_meta.is_stale is False
    assert updated_meta.fetch_count == 1
    assert updated_meta.provider_used == "yfinance"
    assert updated_meta.error_count == 0


async def test_update_meta_error_increments_error_count(cache_manager, seeded_ticker, session):
    meta = await cache_manager._get_or_create_meta("AAPL", "price_history")
    await cache_manager._update_meta_error(meta)
    await cache_manager._update_meta_error(meta)

    from sqlalchemy import select

    stmt = select(CacheMetadata).where(CacheMetadata.id == meta.id)
    result = await session.execute(stmt)
    updated = result.scalar_one()
    assert updated.error_count == 2
