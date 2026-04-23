"""Tests for get_cache_status MCP tool"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from investorai_mcp.db.models import CacheMetadata


@pytest.fixture(autouse=True)
def register_tools():
    from investorai_mcp.server import _register_tools

    _register_tools()


def make_meta(data_tyoe, is_stale=False, error_count=0, fetch_count=3, provider_used="yfinance"):
    meta = MagicMock(spec=CacheMetadata)
    meta.data_type = data_tyoe
    meta.is_stale = is_stale
    meta.last_fetched = datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)
    meta.ttl_seconds = 86400
    meta.fetch_count = fetch_count
    meta.error_count = error_count
    meta.provider_used = provider_used
    return meta


def patch_session(rows):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return patch(
        "investorai_mcp.tools.get_cache_status.AsyncSessionLocal",
        return_value=mock_session,
    )


async def test_unsupported_ticker_returns_error():
    from investorai_mcp.tools.get_cache_status import get_cache_status

    result = await get_cache_status("FAKECROP")
    assert result["error"] is True
    assert result["code"] == "TICKER_NOT_SUPPORTED"


async def test_never_fetched_returns_status():
    from investorai_mcp.tools.get_cache_status import get_cache_status

    with patch_session([]):
        result = await get_cache_status("AAPL")
    assert result["status"] == "never_fetched"
    assert result["entries"] == []


async def test_fresh_status_when_all_fresh():
    from investorai_mcp.tools.get_cache_status import get_cache_status

    rows = [
        make_meta("price_history", is_stale=False),
        make_meta("news", is_stale=False),
    ]
    with patch_session(rows):
        result = await get_cache_status("AAPL")
    assert result["status"] == "fresh"


async def test_stale_status_when_any_stale():
    from investorai_mcp.tools.get_cache_status import get_cache_status

    rows = [
        make_meta("price_history", is_stale=True),
        make_meta("news", is_stale=False),
    ]
    with patch_session(rows):
        result = await get_cache_status("AAPL")
    assert result["status"] == "stale"


async def test_entries_have_required_fields():
    from investorai_mcp.tools.get_cache_status import get_cache_status

    rows = [make_meta("price_history")]
    with patch_session(rows):
        result = await get_cache_status("AAPL")
    entry = result["entries"][0]
    for field in [
        "data_type",
        "is_stale",
        "last_fetched",
        "age_hours",
        "ttl_hours",
        "fetch_count",
        "error_count",
        "provider_used",
    ]:
        assert field in entry, f"{field} missing from entry"


async def test_symbol_normalised_uppercase():
    from investorai_mcp.tools.get_cache_status import get_cache_status

    with patch_session([]):
        result = await get_cache_status("aapl")
    assert result["symbol"] == "AAPL"


async def test_ttl_reference_included():
    from investorai_mcp.tools.get_cache_status import get_cache_status

    rows = [make_meta("price_history")]
    with patch_session(rows):
        result = await get_cache_status("AAPL")
    assert "ttl_reference" in result
    assert "price_history" in result["ttl_reference"]
