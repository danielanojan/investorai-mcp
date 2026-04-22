### ---- Tickers ---------------------------------------
"""
Tests for the FastAPI BFF endpoints
"""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

@pytest.fixture
def app():
    from investorai_mcp.api import create_app
    return create_app()

@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport= ASGITransport(app=app), 
        base_url="http://test"
    ) as c:
        yield c
        
#------- Health ------------------------------------------

async def test_health_returns_ok(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

#------ Tickers ---------------------------------------

async def test_list_tickers_returns_50(client):
    response = await client.get("/api/tickers")
    assert response.status_code == 200
    assert response.json()["total"] == 50

async def test_search_tickers(client):
    response = await client.get("/api/tickers/search?q=AAPL")
    assert response.status_code == 200
    symbols = [m["symbol"] for m in response.json()["matches"]]
    assert "AAPL" in symbols

async def test_search_tickers_missing_q(client):
    response = await client.get("/api/tickers/search")
    assert response.status_code == 422  # Missing required query parameter


# ------- Stock data ---------------------------------------
async def test_prices_unsupported_ticker(client):
    response = await client.get("/api/stocks/FAKE/prices")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TICKER_NOT_SUPPORTED"

async def test_prices_supported_ticker(client):
    mock_result = {
        "symbol": "AAPL", "range": "1Y",
        "prices": [], "total_days": 0,
        "is_stale": False, "data_age_hours": 1.0,
    }
    with patch(
        "investorai_mcp.tools.get_price_history.get_price_history",
        new = AsyncMock(return_value=mock_result)
    ):
        response = await client.get("/api/stocks/AAPL/prices")
        assert response.status_code == 200

async def test_summary_unsupported_ticker(client):
    response = await client.get("/api/stocks/FAKE/summary")
    assert response.status_code == 404

async def test_news_unsupported_ticker(client):
    response = await client.get("/api/stocks/FAKECORP/news")
    assert response.status_code == 404


async def test_cache_unsupported_ticker(client):
    response = await client.get("/api/stocks/FAKECORP/cache")
    assert response.status_code == 404


async def test_sentiment_unsupported_ticker(client):
    response = await client.get("/api/stocks/FAKECORP/sentiment")
    assert response.status_code == 404

### ----- AI Endpoints ---------------------------------------

async def test_trend_unsupported_ticker(client):
    response = await client.post(
        "/api/stocks/FAKECROP/trend",
        json={"question": "Is the stock FakeCrop going up?"}
    )
    assert response.status_code == 404

async def test_chat_missing_question(client):
    response = await client.post("/api/chat", json={"ticker": "AAPL"})
    assert response.status_code == 400  # Missing required field
    assert response.json()["error"]["code"] == "MISSING_QUESTION"

async def test_llm_validate_missing_key(client):
    response = await client.post("/api/llm/validate", json={})
    assert response.status_code == 400  # Missing required field
    assert response.json()["error"]["code"] == "MISSING_KEY"

async def test_refresh_unsupported_ticker(client):
    response = await client.post("/api/stocks/FAKECROP/refresh")
    assert response.status_code == 404

### ----- Symbol Normalization ---------------------------------------
async def test_lowercase_symbol_normalised(client):
    response = await client.get("/api/stocks/fakecrop/prices")
    assert response.status_code == 404
    assert "FAKECROP" in response.json()["error"]["message"]
    
    
    