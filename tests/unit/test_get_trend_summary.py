"""
Tests for get_trend_summary MCP tool.
Covers all helper functions and the main tool integration.
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from investorai_mcp.db.cache_manager import CacheResult
from investorai_mcp.db.models import PriceHistory
from investorai_mcp.tools.get_trend_summary import (
    _detect_all_symbols_from_question,
    _detect_range_from_question,
    _detect_sector_from_question,
    _extract_date_context,
    _handle_meta_question,
    _is_news_question,
    _range_for_date,
    _resolve_absolute_date,
    _resolve_date_range,
    _resolve_relative_date,
)


@pytest.fixture(autouse=True)
def register_tools():
    from investorai_mcp.server import _register_tools
    _register_tools()


def make_row(d: date, price: float) -> PriceHistory:
    row = MagicMock(spec=PriceHistory)
    row.date      = d
    row.adj_close = price
    row.volume    = 50_000_000
    return row


def make_cache_result(rows, is_stale=False):
    return CacheResult(
        data=rows,
        is_stale=is_stale,
        data_age_hours=1.0,
        provider_used="yfinance",
    )


def make_mock_session():
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__  = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)
    return mock_session


def patch_pipeline(
    llm_response="AAPL rose 16.21% [source: DB • 2026-03-28].",
    rows=None,
):
    if rows is None:
        rows = [
            make_row(date(2025, 4,  1), 150.0),
            make_row(date(2026, 3, 28), 174.32),
        ]
    mock_session = make_mock_session()
    mock_manager = MagicMock()
    mock_manager.ensure_ticker_exists = AsyncMock()
    mock_manager.get_prices = AsyncMock(return_value=make_cache_result(rows))
    return (
        patch("investorai_mcp.tools.get_trend_summary.AsyncSessionLocal",
              return_value=mock_session),
        patch("investorai_mcp.tools.get_trend_summary.CacheManager",
              return_value=mock_manager),
        patch("investorai_mcp.tools.get_trend_summary.call_llm",
              new=AsyncMock(return_value=llm_response)),
    )


# ── _detect_range_from_question ───────────────────────────────────────────

def test_range_this_year():
    assert _detect_range_from_question("How has AAPL done this year?") == "1Y"

def test_range_last_year():
    assert _detect_range_from_question("What happened last year?") == "1Y"

def test_range_6_months():
    assert _detect_range_from_question("average over 6 months?") == "6M"

def test_range_3_months():
    assert _detect_range_from_question("last 3 months") == "3M"

def test_range_1_month():
    assert _detect_range_from_question("what happened last month?") == "1M"

def test_range_1_week():
    assert _detect_range_from_question("what happened this week?") == "1W"

def test_range_5_year():
    assert _detect_range_from_question("5 year performance") == "5Y"

def test_range_3_year():
    assert _detect_range_from_question("3 year history") == "3Y"

def test_range_none():
    assert _detect_range_from_question("how is the stock doing?") is None

def test_range_quarter():
    assert _detect_range_from_question("this quarter's performance") == "3M"


# ── _detect_sector_from_question ──────────────────────────────────────────

def test_sector_technology():
    results = _detect_sector_from_question("how is the tech sector doing?")
    assert len(results) > 0
    from investorai_mcp.stocks import SUPPORTED_TICKERS
    for sym in results:
        assert SUPPORTED_TICKERS[sym]["sector"] == "Technology"

def test_sector_finance():
    results = _detect_sector_from_question("how are banking stocks doing?")
    assert len(results) > 0

def test_sector_healthcare():
    results = _detect_sector_from_question("how is healthcare performing?")
    assert len(results) > 0

def test_sector_energy():
    results = _detect_sector_from_question("how is the energy sector?")
    assert len(results) > 0

def test_sector_none():
    results = _detect_sector_from_question("how is AAPL doing?")
    assert results == []

def test_sector_limit():
    results = _detect_sector_from_question("how is the tech sector?")
    assert len(results) <= 6


# ── _detect_all_symbols_from_question ─────────────────────────────────────

def test_detect_single_symbol():
    assert "TSLA" in _detect_all_symbols_from_question("How is TSLA doing?")

def test_detect_multiple_symbols():
    result = _detect_all_symbols_from_question("Compare AAPL and MSFT")
    assert "AAPL" in result
    assert "MSFT" in result

def test_detect_company_name_apple():
    result = _detect_all_symbols_from_question("How is Apple performing?")
    assert "AAPL" in result

def test_detect_company_name_microsoft():
    result = _detect_all_symbols_from_question("What about Microsoft?")
    assert "MSFT" in result

def test_detect_three_companies():
    result = _detect_all_symbols_from_question(
        "Compare Tesla, Apple and Microsoft"
    )
    assert "TSLA" in result
    assert "AAPL" in result
    assert "MSFT" in result

def test_detect_no_symbols():
    result = _detect_all_symbols_from_question("How is the stock doing?")
    assert result == []

def test_detect_nvidia():
    result = _detect_all_symbols_from_question("Tell me about NVDA")
    assert "NVDA" in result


# ── _handle_meta_question ─────────────────────────────────────────────────

def test_meta_today():
    result = _handle_meta_question("what is today's date?")
    assert result is not None
    assert "Today is" in result["summary"]

def test_meta_what_day():
    result = _handle_meta_question("what day is it?")
    assert result is not None

def test_meta_supported_stocks():
    result = _handle_meta_question("what stocks do you support?")
    assert result is not None
    assert "50" in result["summary"]

def test_meta_sectors_covered():
    result = _handle_meta_question("what sectors do you cover?")
    assert result is not None
    assert "sector" in result["summary"].lower()

def test_meta_data_range():
    result = _handle_meta_question("how far back does your data go?")
    assert result is not None
    assert "5 years" in result["summary"]

def test_meta_none_for_stock_question():
    result = _handle_meta_question("How is AAPL doing?")
    assert result is None

def test_meta_validation_always_passed():
    result = _handle_meta_question("what stocks do you support?")
    assert result["validation_passed"] is True


# ── _is_news_question ─────────────────────────────────────────────────────

def test_is_news_question_news():
    assert _is_news_question("what is the latest news on AAPL?") is True

def test_is_news_question_headline():
    assert _is_news_question("show me headlines for TSLA") is True

def test_is_news_question_announcement():
    assert _is_news_question("any announcements from Apple?") is True

def test_is_not_news_question():
    assert _is_news_question("how has AAPL performed this year?") is False

def test_is_not_news_price_question():
    assert _is_news_question("what was the price last Monday?") is False


# ── _resolve_relative_date ────────────────────────────────────────────────

def test_relative_yesterday():
    result   = _resolve_relative_date("what was the price yesterday?")
    expected = datetime.now(timezone.utc).date() - timedelta(days=1)
    assert result == expected

def test_relative_last_monday():
    result = _resolve_relative_date("price last Monday")
    assert result is not None
    assert result.weekday() == 0

def test_relative_last_wednesday():
    result = _resolve_relative_date("price last Wednesday")
    assert result is not None
    assert result.weekday() == 2

def test_relative_last_friday():
    result = _resolve_relative_date("price last Friday")
    assert result is not None
    assert result.weekday() == 4

def test_relative_last_wed_abbr():
    result = _resolve_relative_date("price last Wed")
    assert result is not None
    assert result.weekday() == 2

def test_relative_today():
    result   = _resolve_relative_date("what is the price today?")
    expected = datetime.now(timezone.utc).date()
    assert result == expected

def test_relative_none():
    assert _resolve_relative_date("how is AAPL doing?") is None

def test_relative_last_monday_is_past():
    result = _resolve_relative_date("price last Monday")
    today  = datetime.now(timezone.utc).date()
    assert result < today


# ── _resolve_absolute_date ────────────────────────────────────────────────

def test_absolute_iso_format():
    result = _resolve_absolute_date("price on 2021-04-22")
    assert result == date(2021, 4, 22)


def test_absolute_month_name():
    result = _resolve_absolute_date("price on April 22 2021")
    assert result == date(2021, 4, 22)

def test_absolute_month_abbr():
    result = _resolve_absolute_date("price on Apr 22 2021")
    assert result == date(2021, 4, 22)

def test_absolute_month_with_comma():
    result = _resolve_absolute_date("price on May 12, 2020")
    assert result == date(2020, 5, 12)

def test_absolute_none():
    assert _resolve_absolute_date("how is AAPL doing?") is None


# ── _resolve_date_range ───────────────────────────────────────────────────

def test_date_range_month_year():
    result = _resolve_date_range("from May 2023 to May 2025")
    assert result is not None
    start, end = result
    assert start.year == 2023
    assert end.year   == 2025

def test_date_range_iso():
    result = _resolve_date_range("from 2023-05-01 to 2025-05-31")
    assert result is not None
    start, end = result
    assert start == date(2023, 5, 1)
    assert end   == date(2025, 5, 31)

def test_date_range_with_dash():
    result = _resolve_date_range("Jan 2024 - Dec 2024")
    assert result is not None
    start, end = result
    assert start.year == 2024
    assert end.year   == 2024

def test_date_range_between():
    result = _resolve_date_range("between Jan 2023 and Mar 2023")
    assert result is not None

def test_date_range_none():
    assert _resolve_date_range("how is AAPL doing?") is None

def test_date_range_start_before_end():
    result = _resolve_date_range("from May 2023 to May 2025")
    assert result is not None
    start, end = result
    assert start < end


# ── _range_for_date ───────────────────────────────────────────────────────

def test_range_for_date_1w():
    target = datetime.now(timezone.utc).date() - timedelta(days=3)
    assert _range_for_date(target) == "1W"

def test_range_for_date_1m():
    target = datetime.now(timezone.utc).date() - timedelta(days=20)
    assert _range_for_date(target) == "1M"

def test_range_for_date_3m():
    target = datetime.now(timezone.utc).date() - timedelta(days=60)
    assert _range_for_date(target) == "3M"

def test_range_for_date_6m():
    target = datetime.now(timezone.utc).date() - timedelta(days=150)
    assert _range_for_date(target) == "6M"

def test_range_for_date_1y():
    target = datetime.now(timezone.utc).date() - timedelta(days=300)
    assert _range_for_date(target) == "1Y"

def test_range_for_date_3y():
    target = datetime.now(timezone.utc).date() - timedelta(days=700)
    assert _range_for_date(target) == "3Y"

def test_range_for_date_5y():
    target = datetime.now(timezone.utc).date() - timedelta(days=1500)
    assert _range_for_date(target) == "5Y"


# ── _extract_date_context ─────────────────────────────────────────────────

def test_extract_two_dates():
    result = _extract_date_context("between Jan 2025 and Mar 2025")
    assert result is not None
    assert "jan" in result.lower()

def test_extract_one_date():
    result = _extract_date_context("what happened in 2025?")
    assert result is not None

def test_extract_none():
    assert _extract_date_context("how is AAPL doing?") is None


# ── get_trend_summary tool ────────────────────────────────────────────────

async def test_unsupported_ticker_returns_error():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    result = await get_trend_summary("FAKECORP")
    assert result["error"] is True
    assert result["code"] == "TICKER_NOT_SUPPORTED"


async def test_meta_question_no_llm_call():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    with patch("investorai_mcp.tools.get_trend_summary.call_llm") as mock_llm:
        result = await get_trend_summary(
            "AAPL",
            question="what stocks do you support?"
        )
    mock_llm.assert_not_called()
    assert "summary" in result


async def test_returns_summary_text():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    p1, p2, p3 = patch_pipeline()
    with p1, p2, p3:
        result = await get_trend_summary("AAPL")
    assert "summary" in result
    assert isinstance(result["summary"], str)


async def test_returns_stats_block():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    p1, p2, p3 = patch_pipeline()
    with p1, p2, p3:
        result = await get_trend_summary("AAPL")
    for field in ["start_price", "end_price", "period_return_pct",
                  "high_price", "low_price", "trading_days"]:
        assert field in result["stats"], f"Missing: {field}"


async def test_returns_citations():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    p1, p2, p3 = patch_pipeline("AAPL rose [source: DB • 2026-03-28].")
    with p1, p2, p3:
        result = await get_trend_summary("AAPL")
    assert isinstance(result["citations"], list)


async def test_validation_passed_present():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    p1, p2, p3 = patch_pipeline()
    with p1, p2, p3:
        result = await get_trend_summary("AAPL")
    assert "validation_passed" in result


async def test_llm_unavailable_returns_error():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    mock_session = make_mock_session()
    mock_manager = MagicMock()
    mock_manager.ensure_ticker_exists = AsyncMock()
    mock_manager.get_prices = AsyncMock(
        return_value=make_cache_result([
            make_row(date(2025, 4, 1), 150.0),
            make_row(date(2026, 3, 28), 174.32),
        ])
    )
    with patch("investorai_mcp.tools.get_trend_summary.AsyncSessionLocal",
               return_value=mock_session), \
         patch("investorai_mcp.tools.get_trend_summary.CacheManager",
               return_value=mock_manager), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(side_effect=RuntimeError("no key"))):
        result = await get_trend_summary("AAPL")
    assert result["error"] is True
    assert result["code"]  == "LLM_UNAVAILABLE"


async def test_empty_data_returns_error():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    mock_session = make_mock_session()
    mock_manager = MagicMock()
    mock_manager.ensure_ticker_exists = AsyncMock()
    mock_manager.get_prices = AsyncMock(
        return_value=make_cache_result([])
    )
    with patch("investorai_mcp.tools.get_trend_summary.AsyncSessionLocal",
               return_value=mock_session), \
         patch("investorai_mcp.tools.get_trend_summary.CacheManager",
               return_value=mock_manager):
        result = await get_trend_summary("AAPL")
    assert result["error"] is True


async def test_specific_date_fast_path():
    """Specific date lookup returns DB price directly without LLM."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    target = date(2026, 3, 28)
    rows   = [make_row(target, 174.32)]
    mock_session = make_mock_session()
    mock_manager = MagicMock()
    mock_manager.ensure_ticker_exists = AsyncMock()
    mock_manager.get_prices = AsyncMock(
        return_value=make_cache_result(rows)
    )
    with patch("investorai_mcp.tools.get_trend_summary.AsyncSessionLocal",
               return_value=mock_session), \
         patch("investorai_mcp.tools.get_trend_summary.CacheManager",
               return_value=mock_manager), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm") as mock_llm:
        result = await get_trend_summary(
            "AAPL",
            question=f"What was the price on 2026-03-28?"
        )
    assert "174.32" in result["summary"]
    mock_llm.assert_not_called()


async def test_news_question_skips_number_validation():
    """News questions bypass the number validator."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    p1, p2, p3 = patch_pipeline(
        llm_response="Apple announced a new product. Revenue was $999B."
    )
    with p1, p2, p3:
        result = await get_trend_summary(
            "AAPL",
            question="What is the latest news on Apple?"
        )
    assert result.get("validation_passed") is True


async def test_symbol_detected_from_question():
    """AAPL loaded but user asks about TSLA — TSLA should be fetched."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    p1, p2, p3 = patch_pipeline(llm_response="TSLA performed well.")
    with p1, p2, p3:
        result = await get_trend_summary(
            "AAPL",
            question="How is TSLA doing?"
        )
    assert result["symbol"] == "TSLA"


async def test_6_month_question_uses_6m_range():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    p1, p2, p3 = patch_pipeline()
    with p1, p2, p3:
        result = await get_trend_summary(
            "AAPL",
            question="What is the average price over 6 months?"
        )
    assert result["range"] == "6M"
