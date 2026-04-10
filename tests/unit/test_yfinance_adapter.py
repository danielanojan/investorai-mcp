from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from investorai_mcp.data.base import NewsRecord, OHLCVRecord, TickerInfoRecord
from investorai_mcp.data.yfinance_adapter import YFinanceAdapter


#patch is used to replace real functions with fakes. 

#fictures - reusable step functions - pytest injects these step functions into tests automatically by matching parameter names. 
#each test which declares an adapter as a parameter gets this object - so that each test gets its own clean instance - no shared state between tests. 
@pytest.fixture
def adapter():
    return YFinanceAdapter()

#here we are building a fake dataframe which looks exactly like yfinance output. 
@pytest.fixture
def sample_ohlcv_df():
    "This will be a minimal dataframe which mimics yfinance output."
    import pandas as pd
    
    idx = pd.to_datetime(["2026-03-26", "2026-03-27", "2026-03-28"])
    return pd.DataFrame({
        "Open": [170.0, 171.0, 172.0],
        "High": [173.0, 174.0, 175.0],
        "Low": [169.0, 170.0, 171.0],
        "Close": [172.0, 173.0, 174.0],
        "Volume": [1_000_000, 1_100_000, 1_200_000],
    }, index=idx)

# how patch works?
# you patch where the function is used - not when its defined. 
#adapter imports _sync_fetch_ohlcv into its own module - so you patch it there. 
#_sync_fetch_ohlcv function calls yfinance over the network - but when we set return_value = sample_ohlcv_df - this mock skips and returns the fake dataframe. 
#then the adapter will run as normal - it process dataframe, build records and filter rows - but with the fake datasource. 

#why we build with block scope : the patch is only active within the with block. after it extits - original function will work with the usuall implementation. 


async def test_fetch_ohlcv_returns_ohlcv_records(adapter, sample_ohlcv_df):
    with patch("investorai_mcp.data.yfinance_adapter._sync_fetch_ohlcv", 
               return_value = sample_ohlcv_df,
    ):
        records = await adapter.fetch_ohlcv("AAPL", period="1Y")
        
    assert len(records) == 3
    assert all(isinstance(r, OHLCVRecord) for r in records)
    
    
async def test_fetch_ohlcv_computes_avg_price_correctly(adapter, sample_ohlcv_df):
    with patch("investorai_mcp.data.yfinance_adapter._sync_fetch_ohlcv",
               return_value = sample_ohlcv_df,
    ):
        records = await adapter.fetch_ohlcv("AAPL", period="1Y")
        
        first = records[0]
        expected_avg = (170.0 + 173.0 + 169.0 + 172.0) / 4
        assert abs(first.avg_price - expected_avg) < 1e-10


async def test_fetch_ohlcv_skips_zero_adj_close(adapter):
    idx = pd.to_datetime(["2026-03-26", "2026-03-27"])
    df = pd.DataFrame(
        {
            "Open": [170.0, 0.0],
            "High": [175.0, 0.0],
            "Low": [169.0, 0.0],
            "Close": [173.0, 0.0],
            "Volume": [50_000_000, 0],
        },
        index=idx,
    )
    with patch("investorai_mcp.data.yfinance_adapter._sync_fetch_ohlcv", 
               return_value=df, 
    ):
        records = await adapter.fetch_ohlcv("AAPL", period="1Y")
        
    assert len(records) == 1
    assert records[0].adj_close == 173.0
    
    
async def test_fetch_ohlcv_empty_dataframe_returns_empty_list(adapter):
    with patch(
        "investorai_mcp.data.yfinance_adapter._sync_fetch_ohlcv",
        return_value=pd.DataFrame(),
    ):
        records = await adapter.fetch_ohlcv("AAPL", period="1Y")
    
    assert records == []
    
    
async def test_fetch_ohlcv_split_factor_defaults_to_one(adapter, sample_ohlcv_df):
    with patch("investorai_mcp.data.yfinance_adapter._sync_fetch_ohlcv", 
               return_value=sample_ohlcv_df,
    ):
        records = await adapter.fetch_ohlcv("AAPL", period="1Y")
    assert all (r.split_factor == 1.0 for r in records)
    
    
async def test_fetch_ticker_info_returns_record(adapter):
    mock_info = {
        "longName": "Apple Inc.",
        "sector": "Technology",
        "exchange": "NASDAQ",
        "marketCap": 2_000_000_000_000,
        "sharesOutstanding": 16_000_000_000,
        "currency": "USD",
    }
    with patch("investorai_mcp.data.yfinance_adapter._sync_fetch_info",
               return_value=mock_info,
    ):
        result = await adapter.fetch_ticker_info("AAPL")
        
    assert result.symbol == "AAPL"
    assert result.name == "Apple Inc."
    assert result.sector == "Technology"
    assert result.market_cap == 2_000_000_000_000
    assert result.currency == "USD"
    
async def test_fetch_news_returns_records(adapter):
    mock_news = [
        {
            "title": "Apple returns record Q1 earnings",
            "publisher": "Reuters",
            "link": "https://www.reuters.com/article/apple-earnings-idUSK",
            "providerPublishTime": 1700000000,
        },
        {
            "title": "Apple vision pro 2 launch is confirmed",
            "publicher": "Bloomberg",
            "link": "https://www.bloomberg.com/news/articles/2026-03",
            "providerPublishTime": 1700003600,
        },
    ]
    with patch ("investorai_mcp.data.yfinance_adapter._sync_fetch_news",
               return_value=mock_news,
    ):
        records = await adapter.fetch_news("AAPL", limit=50)
    assert len(records) == 2
    assert all(isinstance(r, NewsRecord) for r in records)
    assert records[0].headline == "Apple returns record Q1 earnings"
    assert records[0].source == "Reuters"
    
async def test_fetch_news_respects_limit(adapter):
    mock_news = [
        {
            "title": f"News {i}",
            "publisher": "Source",
            "link": f"https://example.com/news{i}",
            "providerPublishTime": 1700000000 + i * 3600,
        }
        for i in range(20)
    ]
    with patch("investorai_mcp.data.yfinance_adapter._sync_fetch_news",
               return_value=mock_news,
    ):
        records = await adapter.fetch_news("AAPL", limit=5)
    assert len(records) == 5
    
    
async def test_fetch_news_empty_returns_empty_list(adapter):
    with patch("investorai_mcp.data.yfinance_adapter._sync_fetch_news",
               return_value=[],
    ):
        records = await adapter.fetch_news("AAPL", limit=50)
    assert records == []
    
    
    
    