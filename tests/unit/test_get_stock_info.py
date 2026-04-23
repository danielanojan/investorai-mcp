from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from investorai_mcp.db.models import Base, Ticker


@pytest.fixture(autouse=True)
async def register_tools():
    from investorai_mcp.server import _register_tools

    _register_tools()


@pytest.fixture
async def mem_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    yield engine
    await engine.dispose()


@pytest.fixture
async def mem_session_factory(mem_engine):
    """Session with AAPL already in the tickers table."""
    S = async_sessionmaker(mem_engine, class_=AsyncSession, expire_on_commit=False)
    async with S() as session:
        session.add(
            Ticker(
                symbol="AAPL",
                name="Apple Inc.",
                sector="Technology",
                exchange="NASDAQ",
                market_cap=2_000_000_000_000,
                shares_outstanding=16_000_000_000,
                currency="USD",
                is_supported=True,
            )
        )
        await session.commit()
        yield session


async def test_unsupported_ticker_returns_error():
    from investorai_mcp.tools.get_stock_info import get_stock_info

    result = await get_stock_info("FAKECROP")
    assert result["error"] is True
    assert result["code"] == "TICKER_NOT_SUPPORTED"


async def test_unsupported_ticer_lowercase():
    from investorai_mcp.tools.get_stock_info import get_stock_info

    result = await get_stock_info("fakecrop")
    assert result["error"] is True


async def test_supported_ticker_not_in_db_returns_static():
    from investorai_mcp.tools.get_stock_info import get_stock_info

    # Patch AsyncSessionLocal to return a session where ticker doesn't exist

    # this creates a mocking of async SQL Alchemy session so you do not have to touch the real DB.

    mock_session = AsyncMock()  # mock object is created where all methods are automatically async compatible. Regular MagicMock would break on AsyncCalls.
    mock_session.get = AsyncMock(return_value=None)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("investorai_mcp.tools.get_stock_info.AsyncSessionLocal", return_value=mock_session):
        result = await get_stock_info("AAPL")

    assert result.get("error") is not True
    assert result["symbol"] == "AAPL"
    assert result["name"] == "Apple Inc."
    assert result["data_source"] == "static"


async def test_supported_ticker_in_db_returns_database(mem_session_factory):
    from investorai_mcp.tools.get_stock_info import get_stock_info

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=await mem_session_factory.get(Ticker, "AAPL"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("investorai_mcp.tools.get_stock_info.AsyncSessionLocal", return_value=mock_session):
        result = await get_stock_info("AAPL")

    assert result["symbol"] == "AAPL"
    assert result["name"] == "Apple Inc."
    assert result["market_cap"] == 2_000_000_000_000.0
    assert result["data_source"] == "database"


async def test_returns_all_required_fields():
    from investorai_mcp.tools.get_stock_info import get_stock_info

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("investorai_mcp.tools.get_stock_info.AsyncSessionLocal", return_value=mock_session):
        result = await get_stock_info("NVDA")

    for field in [
        "symbol",
        "name",
        "sector",
        "exchange",
        "currency",
        "is_supported",
    ]:
        assert field in result, f"Expected field '{field}' not found in result"


async def test_symbol_normalised_to_uppercase():
    from investorai_mcp.tools.get_stock_info import get_stock_info

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("investorai_mcp.tools.get_stock_info.AsyncSessionLocal", return_value=mock_session):
        result = await get_stock_info("msft")

    assert result["symbol"] == "MSFT"


async def test_brk_b_supported():
    from investorai_mcp.tools.get_stock_info import get_stock_info

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("investorai_mcp.tools.get_stock_info.AsyncSessionLocal", return_value=mock_session):
        result = await get_stock_info("BRK-B")

    assert "error" not in result or result.get("error") is not True
    assert result["symbol"] == "BRK-B"
