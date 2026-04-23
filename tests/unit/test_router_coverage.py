"""Router unit tests — covers paths not hit by test_api.py.

test_api.py covers: 404 paths, missing-field 400s, ticker normalisation.
This file covers: tool mock success paths, SSE stream, validate, _percentile,
monitoring/latency, monitoring/langfuse.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    from investorai_mcp.api import create_app

    return create_app()


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# _percentile (pure function — no HTTP needed)
# ---------------------------------------------------------------------------


def test_percentile_empty_returns_zero():
    from investorai_mcp.api.router import _percentile

    assert _percentile([], 50) == 0


def test_percentile_single_value():
    from investorai_mcp.api.router import _percentile

    assert _percentile([100], 50) == 100
    assert _percentile([100], 99) == 100


def test_percentile_p50():
    from investorai_mcp.api.router import _percentile

    values = sorted([10, 20, 30, 40, 50])
    assert _percentile(values, 50) == 30


def test_percentile_p99_returns_near_max():
    from investorai_mcp.api.router import _percentile

    values = sorted(range(1, 101))
    assert _percentile(values, 99) == 99


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


async def test_health_ok(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "provider" in body
    assert "checks" in body
    assert body["checks"]["db"]["status"] == "ok"
    assert "latency_ms" in body["checks"]["db"]
    assert "llm" in body["checks"]


async def test_health_db_down_returns_503(client):
    from unittest.mock import patch

    with patch(
        "investorai_mcp.db.AsyncSessionLocal",
        return_value=_FakeErrorCtx(),
    ):
        response = await client.get("/api/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["db"]["status"] == "error"


class _FakeErrorCtx:
    async def __aenter__(self):
        raise RuntimeError("DB down")

    async def __aexit__(self, *a):
        pass


# ---------------------------------------------------------------------------
# Tickers
# ---------------------------------------------------------------------------


async def test_list_tickers_shape(client):
    response = await client.get("/api/tickers")
    assert response.status_code == 200
    body = response.json()
    assert "tickers" in body
    assert "total" in body
    assert body["total"] == len(body["tickers"])
    first = body["tickers"][0]
    assert all(k in first for k in ("symbol", "name", "sector", "exchange"))


async def test_search_tickers_returns_match(client):
    response = await client.get("/api/tickers/search?q=AAPL")
    assert response.status_code == 200
    symbols = [m["symbol"] for m in response.json()["matches"]]
    assert "AAPL" in symbols


async def test_search_tickers_no_match_returns_empty(client):
    response = await client.get("/api/tickers/search?q=ZZZZNOTREAL")
    assert response.status_code == 200
    assert response.json()["matches"] == []


# ---------------------------------------------------------------------------
# Stock data — success paths (tool mocked)
# ---------------------------------------------------------------------------


async def test_prices_success(client):
    mock_result = {
        "symbol": "AAPL",
        "range": "1Y",
        "prices": [{"date": "2026-01-01", "adj_close": 150.0}],
        "total_days": 1,
        "is_stale": False,
        "data_age_hours": 1.0,
    }
    with patch(
        "investorai_mcp.tools.get_price_history.get_price_history",
        new=AsyncMock(return_value=mock_result),
    ):
        response = await client.get("/api/stocks/AAPL/prices")
    assert response.status_code == 200
    assert response.json()["symbol"] == "AAPL"


async def test_prices_tool_error_returns_503(client):
    error_result = {"error": True, "code": "NO_DATA", "message": "No prices found."}
    with patch(
        "investorai_mcp.tools.get_price_history.get_price_history",
        new=AsyncMock(return_value=error_result),
    ):
        response = await client.get("/api/stocks/AAPL/prices")
    assert response.status_code == 503


async def test_summary_success(client):
    mock_result = {
        "symbol": "AAPL",
        "range": "1Y",
        "start_price": 140.0,
        "end_price": 180.0,
        "period_return_pct": 28.57,
        "high_price": 190.0,
        "low_price": 130.0,
        "avg_price": 160.0,
        "volatality_pct": 1.2,
        "trading_days": 252,
        "is_stale": False,
    }
    with patch(
        "investorai_mcp.tools.get_daily_summary.get_daily_summary",
        new=AsyncMock(return_value=mock_result),
    ):
        response = await client.get("/api/stocks/AAPL/summary")
    assert response.status_code == 200
    assert response.json()["symbol"] == "AAPL"


async def test_summary_tool_error_returns_503(client):
    error_result = {"error": True, "code": "NO_DATA", "message": "empty"}
    with patch(
        "investorai_mcp.tools.get_daily_summary.get_daily_summary",
        new=AsyncMock(return_value=error_result),
    ):
        response = await client.get("/api/stocks/AAPL/summary")
    assert response.status_code == 503


async def test_news_success(client):
    mock_result = {"symbol": "AAPL", "articles": [], "count": 0}
    with patch("investorai_mcp.tools.get_news.get_news", new=AsyncMock(return_value=mock_result)):
        response = await client.get("/api/stocks/AAPL/news")
    assert response.status_code == 200


async def test_news_tool_error_returns_503(client):
    error_result = {"error": True, "code": "DB_ERROR", "message": "db failure"}
    with patch("investorai_mcp.tools.get_news.get_news", new=AsyncMock(return_value=error_result)):
        response = await client.get("/api/stocks/AAPL/news")
    assert response.status_code == 503


async def test_sentiment_success(client):
    mock_result = {
        "symbol": "AAPL",
        "overall": "positive",
        "score": 1,
        "reasoning": "good",
        "key_themes": [],
        "articles_analyzed": 3,
    }
    with patch(
        "investorai_mcp.tools.get_sentiment.get_sentiment", new=AsyncMock(return_value=mock_result)
    ):
        response = await client.get("/api/stocks/AAPL/sentiment")
    assert response.status_code == 200
    assert response.json()["overall"] == "positive"


async def test_cache_success(client):
    mock_result = {"symbol": "AAPL", "overall_status": "fresh", "entries": []}
    with patch(
        "investorai_mcp.tools.get_cache_status.get_cache_status",
        new=AsyncMock(return_value=mock_result),
    ):
        response = await client.get("/api/stocks/AAPL/cache")
    assert response.status_code == 200


async def test_refresh_success(client):
    mock_result = {
        "symbol": "AAPL",
        "success": True,
        "records_loaded": 100,
        "is_stale": False,
        "provider_used": "yfinance",
        "refreshed_at": "2026-04-22T00:00:00Z",
        "message": "ok",
    }
    with patch(
        "investorai_mcp.tools.refresh_ticker.refresh_ticker",
        new=AsyncMock(return_value=mock_result),
    ):
        response = await client.post("/api/stocks/AAPL/refresh")
    assert response.status_code == 200
    assert response.json()["success"] is True


# ---------------------------------------------------------------------------
# LLM validate
# ---------------------------------------------------------------------------


async def test_llm_validate_success(client):
    mock_response = AsyncMock()
    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        response = await client.post(
            "/api/llm/validate",
            json={"api_key": "sk-test-valid", "model": "claude-sonnet-4-20250514"},
        )
    assert response.status_code == 200
    assert response.json()["valid"] is True


async def test_llm_validate_bad_key_returns_400(client):
    with patch("litellm.acompletion", new=AsyncMock(side_effect=Exception("auth error"))):
        response = await client.post(
            "/api/llm/validate",
            json={"api_key": "sk-bad"},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "LLM_KEY_INVALID"


# ---------------------------------------------------------------------------
# /chat/stream — SSE
# ---------------------------------------------------------------------------


async def _read_sse_events(response) -> list[dict]:
    """Parse SSE data lines from a streaming response."""
    events = []
    async for line in response.aiter_lines():
        if line.startswith("data: "):
            raw = line[6:].strip()
            if raw:
                events.append(json.loads(raw))
    return events


async def _make_generator(*event_dicts):
    """Build an async generator that yields the given dicts."""

    async def _gen():
        for e in event_dicts:
            yield e

    return _gen()


async def test_chat_stream_missing_question_returns_400(client):
    response = await client.post(
        "/api/chat/stream",
        json={"symbol": "AAPL"},
        headers={"X-LLM-API-Key": "sk-test"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MISSING_QUESTION"


async def test_chat_stream_missing_api_key_returns_400(client):
    with patch("investorai_mcp.config.settings") as mock_settings:
        mock_settings.llm_api_key = None
        mock_settings.ai_chat_enabled = True
        response = await client.post(
            "/api/chat/stream",
            json={"symbol": "AAPL", "question": "How is AAPL?"},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MISSING_API_KEY"


async def test_chat_stream_unsupported_ticker_returns_404(client):
    response = await client.post(
        "/api/chat/stream",
        json={"symbol": "FAKECORP", "question": "How is it?"},
        headers={"X-LLM-API-Key": "sk-test"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TICKER_NOT_SUPPORTED"


async def test_chat_stream_yields_start_token_done(client):
    async def fake_agent_loop(**kwargs):
        yield {"type": "token", "content": "Apple "}
        yield {"type": "token", "content": "is good."}
        yield {"type": "done"}

    with (
        patch("investorai_mcp.llm.agent.run_agent_loop", new=fake_agent_loop),
        patch("investorai_mcp.api.router._log_chat_request", new=AsyncMock()),
    ):
        async with client.stream(
            "POST",
            "/api/chat/stream",
            json={"symbol": "AAPL", "question": "How is AAPL?"},
            headers={"X-LLM-API-Key": "sk-test"},
        ) as response:
            assert response.status_code == 200
            events = await _read_sse_events(response)

    types = [e["type"] for e in events]
    assert "start" in types
    assert "token" in types
    assert "done" in types


async def test_chat_stream_yields_thinking_event(client):
    async def fake_agent_loop(**kwargs):
        yield {"type": "thinking", "tools": ["get_price_history"], "iteration": 1}
        yield {"type": "token", "content": "Answer."}
        yield {"type": "done"}

    with (
        patch("investorai_mcp.llm.agent.run_agent_loop", new=fake_agent_loop),
        patch("investorai_mcp.api.router._log_chat_request", new=AsyncMock()),
    ):
        async with client.stream(
            "POST",
            "/api/chat/stream",
            json={"symbol": "AAPL", "question": "How is AAPL?"},
            headers={"X-LLM-API-Key": "sk-test"},
        ) as response:
            events = await _read_sse_events(response)

    thinking = [e for e in events if e["type"] == "thinking"]
    assert len(thinking) == 1
    assert "get_price_history" in thinking[0]["tools"]


async def test_chat_stream_agent_exception_yields_error_event(client):
    async def fake_agent_loop(**kwargs):
        raise RuntimeError("agent exploded")
        yield  # make it a generator

    with (
        patch("investorai_mcp.llm.agent.run_agent_loop", new=fake_agent_loop),
        patch("investorai_mcp.api.router._log_chat_request", new=AsyncMock()),
    ):
        async with client.stream(
            "POST",
            "/api/chat/stream",
            json={"symbol": "AAPL", "question": "How is AAPL?"},
            headers={"X-LLM-API-Key": "sk-test"},
        ) as response:
            assert response.status_code == 200
            events = await _read_sse_events(response)

    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) == 1


async def test_chat_stream_no_token_yields_error_event(client):
    async def fake_agent_loop(**kwargs):
        yield {"type": "done"}  # done with no token — no response generated

    with (
        patch("investorai_mcp.llm.agent.run_agent_loop", new=fake_agent_loop),
        patch("investorai_mcp.api.router._log_chat_request", new=AsyncMock()),
    ):
        async with client.stream(
            "POST",
            "/api/chat/stream",
            json={"symbol": "AAPL", "question": "How is AAPL?"},
            headers={"X-LLM-API-Key": "sk-test"},
        ) as response:
            events = await _read_sse_events(response)

    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) == 1
    assert "No response" in error_events[0]["message"]


async def test_chat_stream_sse_headers(client):
    async def fake_agent_loop(**kwargs):
        yield {"type": "token", "content": "hi"}
        yield {"type": "done"}

    with (
        patch("investorai_mcp.llm.agent.run_agent_loop", new=fake_agent_loop),
        patch("investorai_mcp.api.router._log_chat_request", new=AsyncMock()),
    ):
        async with client.stream(
            "POST",
            "/api/chat/stream",
            json={"symbol": "AAPL", "question": "hi"},
            headers={"X-LLM-API-Key": "sk-test"},
        ) as response:
            ct = response.headers.get("content-type", "")

    assert "text/event-stream" in ct


# ---------------------------------------------------------------------------
# Monitoring — /monitoring/langfuse
# ---------------------------------------------------------------------------


async def test_langfuse_not_configured_returns_503(client):
    with patch("investorai_mcp.config.settings") as mock_settings:
        mock_settings.langfuse_public_key = None
        mock_settings.langfuse_secret_key = None
        mock_settings.langfuse_host = "https://cloud.langfuse.com"
        response = await client.get("/api/monitoring/langfuse")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LANGFUSE_NOT_CONFIGURED"


async def test_langfuse_http_host_rejected(client):
    with patch("investorai_mcp.config.settings") as mock_settings:
        mock_settings.langfuse_public_key = "pk-test"
        mock_settings.langfuse_secret_key = "sk-test"  # noqa: S105
        mock_settings.langfuse_host = "http://insecure.langfuse.com"
        response = await client.get("/api/monitoring/langfuse")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_LANGFUSE_HOST"


# ---------------------------------------------------------------------------
# Monitoring — /monitoring/latency
# ---------------------------------------------------------------------------


async def test_latency_endpoint_empty_db(client):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from investorai_mcp.db.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    real_session = Session()

    class _FakeCtx:
        async def __aenter__(self):
            return real_session

        async def __aexit__(self, *a):
            await real_session.close()

    with patch("investorai_mcp.db.AsyncSessionLocal", return_value=_FakeCtx()):
        response = await client.get("/api/monitoring/latency")

    await engine.dispose()
    assert response.status_code == 200
    body = response.json()
    assert body["total_calls"] == 0
    assert body["outliers"] == []
