#integration test for pre-population script

import os
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from investorai_mcp.data.base import OHLCVRecord
from investorai_mcp.db.models import Base, PriceHistory, Ticker, CacheMetadata
from investorai_mcp.stocks import SUPPORTED_TICKERS 


def make_ohlcv(symbol="AAPL", d=None, price=174.0):
    return OHLCVRecord(
        symbol=symbol,
        date=d or date(2026, 3, 28),
        open=172.0,
        high=176.0,
        low=170.0,
        close=price,
        adj_close=price,
        avg_price=(172.0 + 176.0 + 170.0 + price) / 4,
        volume=50_000_000,
    )
    
    
@pytest.fixture
async def mem_engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    yield eng
    await eng.dispose()
    
    
@pytest.fixture
async def mem_session(mem_engine):
    S = async_sessionmaker(mem_engine, class_=AsyncSession, expire_on_commit=False)
    async with S() as s:
        yield s
        
@pytest.fixture
def mock_adapter():
    adapter = MagicMock()
    adapter.fetch_ohlcv = AsyncMock(return_value=[make_ohlcv()])
    adapter.fetch_news = AsyncMock(return_value=[])
    adapter.fetch_ticker_info = AsyncMock()
    return adapter


################# Tests for populate.py #################

async def test_populate_ticker_creates_ticker_row(mem_session, mock_adapter):
    from investorai_mcp.db.cache_manager import CacheManager
    from scripts.prepopulate import populate_ticker
    
    ok, count = await populate_ticker("AAPL", mem_session, mock_adapter, dry_run=False)
    
    assert ok is True
    ticker = await mem_session.get(Ticker, "AAPL")
    assert ticker is not None
    assert ticker.name == "Apple Inc."
    
async def test_populate_ticker_writes_price_rows(mem_session, mock_adapter):
    from scripts.prepopulate import populate_ticker
    
    mock_adapter.fetch_ohlcv.return_value = [
        make_ohlcv(d=date(2026, 3, 26), price=174.0),
        make_ohlcv(d=date(2026, 3, 27), price=174.0),
        make_ohlcv(d=date(2026, 3, 28), price=176.0),
    ]
    
    ok, count = await populate_ticker("AAPL", mem_session, mock_adapter, dry_run=False)
    
    assert ok is True
    assert count == 3
    
    stmt = select(PriceHistory).where(PriceHistory.symbol == "AAPL")
    result = await mem_session.execute(stmt)
    prices = result.scalars().all()
    assert len(prices) == 3
    
async def test_populate_ticker_marks_cache_fresh(mem_session, mock_adapter):
    from scripts.prepopulate import populate_ticker
    
    await populate_ticker("AAPL", mem_session, mock_adapter, dry_run=False)
    stmt = select(CacheMetadata).where(CacheMetadata.symbol == "AAPL", CacheMetadata.data_type == "price_history")
    
    result = await mem_session.execute(stmt)
    meta = result.scalar_one_or_none()
    assert meta is not None
    assert meta.is_stale is False
    assert meta.fetch_count == 1
    assert meta.provider_used == "yfinance"
    
async def test_populate_ticker_dry_run_does_not_write(mem_session, mock_adapter):
    from scripts.prepopulate import populate_ticker
    
    ok, count = await populate_ticker("AAPL", mem_session, mock_adapter, dry_run=True)
    
    assert ok is True
    assert count == 0
    mock_adapter.fetch_ohlcv.assert_not_called()
    
    stmt = select(PriceHistory).where(PriceHistory.symbol == "AAPL")
    result = await mem_session.execute(stmt)
    assert result.scalars().all() == []
    
    
async def test_populate_ticker_unsupported_returns_false(mem_session, mock_adapter):
    from scripts.prepopulate import populate_ticker
    
    ok, count = await populate_ticker("FAKECROP", mem_session, mock_adapter, dry_run=False)
    
    assert ok is False
    assert count == 0
    
    
async def test_populate_ticker_empty_response_returns_false(mem_session, mock_adapter):
    from scripts.prepopulate import populate_ticker
    
    mock_adapter.fetch_ohlcv.return_value = []
    
    ok, count = await populate_ticker("AAPL", mem_session, mock_adapter, dry_run=False)
    
    assert ok is False
    assert count == 0
    
async def test_populate_ticker_idempotent(mem_session, mock_adapter):
    """running populate twice for the same ticker must not duplicate rows."""
    from scripts.prepopulate import populate_ticker
    
    mock_adapter.fetch_ohlcv.return_value = [make_ohlcv(d=date(2026, 3, 26))]
    
    
    #run twice
    await populate_ticker("AAPL", mem_session, mock_adapter, dry_run=False)
    await populate_ticker("AAPL", mem_session, mock_adapter, dry_run=False)
    
    stmt = select(PriceHistory).where(PriceHistory.symbol == "AAPL")
    result = await mem_session.execute(stmt)
    rows = result.scalars().all()
    assert len(rows) == 1   # upsert - there should be no duplicates
    
    
async def test_all_50_tickers_in_supported_list():
    """Sanity check - the script will attempt exactly 50 tickers"""
    assert len(SUPPORTED_TICKERS) == 50
    
    
