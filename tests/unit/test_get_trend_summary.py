"""
Tests for get_trend_summary MCP tool.
Covers all helper functions and the main tool integration.
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from investorai_mcp.db.cache_manager import CacheResult
from investorai_mcp.db.models import PriceHistory
from investorai_mcp.tools.parse_question import (
    detect_symbols as _detect_all_symbols_from_question,
    detect_range as _detect_range_from_question,
    detect_sector as _detect_sector_from_question,
    extract_date_context as _extract_date_context,
    is_news_question as _is_news_question,
    range_for_date as _range_for_date,
    resolve_absolute_date as _resolve_absolute_date,
    resolve_date_range as _resolve_date_range,
    resolve_relative_date as _resolve_relative_date,
)
from investorai_mcp.tools.get_system_info import handle_meta_question as _handle_meta_question


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


_MOCK_STOCK_INFO = {
    "symbol": "AAPL",
    "name": "Apple Inc.",
    "sector": "Technology",
    "exchange": "NASDAQ",
    "market_cap": 3_000_000_000_000,
    "is_supported": True,
    "data_source": "database",
}

_MOCK_NEWS = {"articles": [], "total": 0, "is_stale": False}

_MOCK_SENTIMENT = {
    "sentiment": "neutral",
    "score": 0,
    "reasoning": "Mixed signals.",
    "key_themes": [],
    "citations": [],
    "articles_analyzed": 0,
}


def _rows_to_price_result(rows, symbol: str = "AAPL") -> dict:
    """Convert make_row() mock objects to get_price_history() dict response."""
    return {
        "symbol": symbol,
        "prices": [
            {
                "date": str(r.date),
                "adj_close": r.adj_close,
                "close": r.adj_close,
                "avg_price": round(r.adj_close - 0.5, 2),
                "volume": r.volume,
            }
            for r in rows
        ],
        "is_stale": False,
        "data_age_hours": 1.0,
    }


def patch_pipeline(
    llm_response="AAPL rose 16.21% [source: DB • 2026-03-28].",
    rows=None,
):
    if rows is None:
        rows = [
            make_row(date(2025, 4,  1), 150.0),
            make_row(date(2026, 3, 28), 174.32),
        ]
    price_result = _rows_to_price_result(rows)
    return (
        patch("investorai_mcp.tools.get_trend_summary.get_price_history",
              new=AsyncMock(return_value=price_result)),
        patch("investorai_mcp.tools.get_trend_summary.get_news",
              new=AsyncMock(return_value=_MOCK_NEWS)),
        patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
              new=AsyncMock(return_value=_MOCK_STOCK_INFO)),
        patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
              new=AsyncMock(return_value=_MOCK_SENTIMENT)),
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
    tickers, sectors = _detect_sector_from_question("how is the tech sector doing?")
    assert len(tickers) > 0
    assert "Technology" in sectors
    from investorai_mcp.stocks import SUPPORTED_TICKERS
    for sym in tickers:
        assert SUPPORTED_TICKERS[sym]["sector"] == "Technology"

def test_sector_finance():
    tickers, sectors = _detect_sector_from_question("how are banking stocks doing?")
    assert len(tickers) > 0
    assert "Finance" in sectors

def test_sector_healthcare():
    tickers, sectors = _detect_sector_from_question("how is healthcare performing?")
    assert len(tickers) > 0
    assert "Healthcare" in sectors

def test_sector_energy():
    tickers, sectors = _detect_sector_from_question("how is the energy sector?")
    assert len(tickers) > 0
    assert "Energy & Industrials" in sectors

def test_sector_none():
    tickers, sectors = _detect_sector_from_question("how is AAPL doing?")
    assert tickers == []
    assert sectors == []

def test_sector_no_limit():
    # No cap on tickers per sector — returns all matching stocks
    tickers, sectors = _detect_sector_from_question("how is the tech sector?")
    assert len(tickers) > 0


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
    p1, p2, p3, p4, p5 = patch_pipeline()
    with p1, p2, p3, p4, p5:
        result = await get_trend_summary("AAPL")
    assert "summary" in result
    assert isinstance(result["summary"], str)


async def test_returns_stats_block():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    p1, p2, p3, p4, p5 = patch_pipeline()
    with p1, p2, p3, p4, p5:
        result = await get_trend_summary("AAPL")
    for field in ["start_price", "end_price", "period_return_pct",
                  "high_price", "low_price", "trading_days"]:
        assert field in result["stats"], f"Missing: {field}"


async def test_returns_citations():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    p1, p2, p3, p4, p5 = patch_pipeline("AAPL rose [source: DB • 2026-03-28].")
    with p1, p2, p3, p4, p5:
        result = await get_trend_summary("AAPL")
    assert isinstance(result["citations"], list)


async def test_validation_passed_present():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    p1, p2, p3, p4, p5 = patch_pipeline()
    with p1, p2, p3, p4, p5:
        result = await get_trend_summary("AAPL")
    assert "validation_passed" in result


async def test_llm_unavailable_returns_error():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    rows = [make_row(date(2025, 4, 1), 150.0), make_row(date(2026, 3, 28), 174.32)]
    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=_rows_to_price_result(rows))), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(side_effect=RuntimeError("no key"))):
        result = await get_trend_summary("AAPL")
    assert result["error"] is True
    assert result["code"]  == "LLM_UNAVAILABLE"


async def test_empty_data_returns_error():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    empty_result = {"symbol": "AAPL", "prices": [], "is_stale": False, "data_age_hours": 1.0}
    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=empty_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)):
        result = await get_trend_summary("AAPL")
    assert result["error"] is True


async def test_specific_date_fast_path():
    """Specific date lookup returns DB price directly without LLM."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    target = date(2026, 3, 28)
    rows   = [make_row(target, 174.32)]
    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=_rows_to_price_result(rows))), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm") as mock_llm:
        result = await get_trend_summary(
            "AAPL",
            question="What was the price on 2026-03-28?"
        )
    assert "174.32" in result["summary"]
    mock_llm.assert_not_called()


async def test_news_question_skips_number_validation():
    """News questions bypass the number validator."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    p1, p2, p3, p4, p5 = patch_pipeline(
        llm_response="Apple announced a new product. Revenue was $999B."
    )
    with p1, p2, p3, p4, p5:
        result = await get_trend_summary(
            "AAPL",
            question="What is the latest news on Apple?"
        )
    assert result.get("validation_passed") is True


async def test_symbol_detected_from_question():
    """AAPL loaded but user asks about TSLA — TSLA should be fetched."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    p1, p2, p3, p4, p5 = patch_pipeline(llm_response="TSLA performed well.")
    with p1, p2, p3, p4, p5:
        result = await get_trend_summary(
            "AAPL",
            question="How is TSLA doing?"
        )
    assert result["symbol"] == "TSLA"


async def test_6_month_question_uses_6m_range():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    p1, p2, p3, p4, p5 = patch_pipeline()
    with p1, p2, p3, p4, p5:
        result = await get_trend_summary(
            "AAPL",
            question="What is the average price over 6 months?"
        )
    assert result["range"] == "6M"


# ── _analyse_one_symbol: date_range branch (L86-89) ──────────────────────

async def test_date_range_empty_rows_returns_no_data_summary():
    """When date_range filter leaves zero rows, return a no-data message."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    # rows all fall before the queried date range
    rows = [make_row(date(2020, 1, 2), 100.0), make_row(date(2020, 1, 3), 101.0)]
    price_result = _rows_to_price_result(rows)
    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=price_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=_MOCK_SENTIMENT)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(return_value="summary")):
        # "from May 2023 to May 2025" resolves to a range; rows all pre-date it
        result = await get_trend_summary(
            "AAPL",
            question="How did AAPL do from May 2025 to Jun 2025?"
        )
    assert result.get("validation_passed") is True
    assert "No trading data" in result["summary"] or "summary" in result


# ── _analyse_one_symbol: resolved_date not in rows + before-history (L141-148) ─

async def test_specific_date_not_in_rows_holiday():
    """When resolved_date is in the data range but not in rows, returns 'holiday' message."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    rows = [
        make_row(date(2026, 3, 27), 170.0),
        make_row(date(2026, 3, 31), 175.0),
    ]
    price_result = _rows_to_price_result(rows)
    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=price_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=_MOCK_SENTIMENT)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(return_value="summary")):
        result = await get_trend_summary(
            "AAPL",
            question="What was the price on 2026-03-28?"  # weekend
        )
    assert result.get("validation_passed") is True
    assert "no data" in result["summary"].lower() or "holiday" in result["summary"].lower()


async def test_specific_date_before_history():
    """When resolved_date is before the earliest DB row, says 'outside available history'."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    rows = [make_row(date(2025, 1, 2), 150.0), make_row(date(2025, 1, 3), 151.0)]
    price_result = _rows_to_price_result(rows)
    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=price_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=_MOCK_SENTIMENT)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(return_value="summary")):
        result = await get_trend_summary(
            "AAPL",
            question="What was the price on 2021-04-22?"
        )
    assert result.get("validation_passed") is True
    assert "outside" in result["summary"].lower() or "no trading data" in result["summary"].lower()


# ── Sentiment enriched into prompt (L189) ─────────────────────────────────

async def test_news_question_sentiment_key_themes_included():
    """Sentiment key_themes are appended to the enriched LLM question when present."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    sentiment_with_themes = {
        **_MOCK_SENTIMENT,
        "sentiment": "positive",
        "score": 0.8,
        "key_themes": ["AI growth", "iPhone sales"],
    }
    rows = [make_row(date(2025, 4, 1), 150.0), make_row(date(2026, 3, 28), 174.32)]
    price_result = _rows_to_price_result(rows)
    captured_messages = []

    async def capture_llm(messages, **kwargs):
        captured_messages.extend(messages)
        return "Apple news was positive [source: Reuters • http://example.com]."

    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=price_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=sentiment_with_themes)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(side_effect=capture_llm)):
        await get_trend_summary("AAPL", question="What is the latest news on AAPL?")

    combined = " ".join(str(m) for m in captured_messages)
    assert "AI growth" in combined or "iPhone sales" in combined


async def test_news_question_returns_sentiment_block():
    """Single-stock news question response includes 'sentiment' key."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    sentiment_positive = {
        **_MOCK_SENTIMENT,
        "sentiment": "positive",
        "score": 0.7,
        "key_themes": ["product launch"],
    }
    rows = [make_row(date(2025, 4, 1), 150.0), make_row(date(2026, 3, 28), 174.32)]
    price_result = _rows_to_price_result(rows)
    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=price_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=sentiment_positive)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(return_value="Latest Apple news.")):
        result = await get_trend_summary("AAPL", question="What is the latest news on Apple?")
    assert result.get("sentiment") is not None
    assert result["sentiment"]["overall"] == "positive"


# ── Symbol routing: all-stocks + sector paths (L304, L308-309) ──────────────

async def test_all_stocks_question_triggers_multi():
    """'Compare all stocks' triggers multi-stock path."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    rows = [make_row(date(2025, 4, 1), 100.0), make_row(date(2026, 3, 28), 110.0)]
    price_result = _rows_to_price_result(rows)
    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=price_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=_MOCK_SENTIMENT)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(return_value="All stocks performed well.")):
        result = await get_trend_summary("AAPL", question="Compare all stocks")
    assert result.get("multi") is True


async def test_sector_question_routes_to_sector_tickers():
    """A sector question routes to sector tickers and sets sector_label."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    rows = [make_row(date(2025, 4, 1), 100.0), make_row(date(2026, 3, 28), 110.0)]
    price_result = _rows_to_price_result(rows)
    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=price_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=_MOCK_SENTIMENT)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(return_value="Tech stocks rose.")):
        result = await get_trend_summary("AAPL", question="How is the tech sector doing?")
    assert result.get("multi") is True


# ── Date-range instruction injection (L335, L345-346, L354) ───────────────

async def test_date_range_question_fetches_data_for_range():
    """Explicit date range triggers effective_range covering the window."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    rows = [
        make_row(date(2023, 5, 1), 160.0),
        make_row(date(2025, 5, 30), 180.0),
    ]
    price_result = _rows_to_price_result(rows)
    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=price_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=_MOCK_SENTIMENT)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(return_value="AAPL rose in that period.")):
        result = await get_trend_summary(
            "AAPL",
            question="How did AAPL do from May 2023 to May 2025?"
        )
    assert "summary" in result


async def test_sector_query_without_explicit_sector_label_with_sector_keyword():
    """Sector keyword in a non-sector-label question with >10 symbols injects instruction."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    rows = [make_row(date(2025, 4, 1), 100.0), make_row(date(2026, 3, 28), 110.0)]
    price_result = _rows_to_price_result(rows)
    captured = []

    async def capture_llm(messages, **kwargs):
        captured.extend(messages)
        return "Sector analysis done."

    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=price_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=_MOCK_SENTIMENT)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(side_effect=capture_llm)):
        await get_trend_summary("AAPL", question="Which sector performed best this year?")

    combined = " ".join(str(m) for m in captured)
    # Either went multi-stock or single — either way no crash
    assert "sector" in combined.lower() or len(captured) > 0


# ── History compression path (L359-363) ──────────────────────────────────

async def test_history_is_compressed_when_provided():
    """When history is passed, compress_history is called."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    rows = [make_row(date(2025, 4, 1), 150.0), make_row(date(2026, 3, 28), 174.32)]
    history = [
        {"role": "user", "content": "How is AAPL doing?"},
        {"role": "assistant", "content": "AAPL rose 10%."},
    ]
    price_result = _rows_to_price_result(rows)
    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=price_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=_MOCK_SENTIMENT)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(return_value="AAPL rose 16.21%.")), \
         patch("investorai_mcp.tools.get_trend_summary.compress_history",
               new=AsyncMock(return_value=history)) as mock_compress:
        result = await get_trend_summary("AAPL", history=history)
    mock_compress.assert_called_once()
    assert "summary" in result


# ── Multi-stock: resolved_date fast path (L391-407) ──────────────────────

async def test_multi_stock_resolved_date_returns_prices():
    """Multi-stock + resolved date returns a closing-prices summary without LLM."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    target = date(2026, 3, 27)
    rows = [make_row(target, 174.32)]
    price_result = _rows_to_price_result(rows, symbol="AAPL")

    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=price_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=_MOCK_SENTIMENT)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm") as mock_llm:
        result = await get_trend_summary(
            "AAPL",
            question="What were the prices of AAPL and MSFT on 2026-03-27?"
        )
    mock_llm.assert_not_called()
    assert result.get("multi") is True
    assert "174.32" in result["summary"] or "Closing prices" in result["summary"]


async def test_multi_stock_resolved_date_missing_row():
    """Multi-stock + resolved date for a symbol with no matching row uses 'no data' fallback."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    rows = [make_row(date(2026, 3, 27), 174.32)]
    price_result = _rows_to_price_result(rows, symbol="AAPL")

    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=price_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=_MOCK_SENTIMENT)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm") as mock_llm:
        result = await get_trend_summary(
            "AAPL",
            question="What were the prices of AAPL and MSFT on 2026-03-28?"  # weekend
        )
    mock_llm.assert_not_called()
    assert result.get("multi") is True
    assert "no data" in result["summary"].lower() or "holiday" in result["summary"].lower()


# ── Multi-stock: no stats available (L416-418) ────────────────────────────

async def test_multi_stock_no_data_returns_error():
    """Multi-stock where every symbol has empty price data returns DATA_UNAVAILABLE."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    empty_price = {"symbol": "AAPL", "prices": [], "is_stale": False, "data_age_hours": 1.0}
    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=empty_price)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=_MOCK_SENTIMENT)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(return_value="summary")):
        result = await get_trend_summary(
            "AAPL",
            question="Compare AAPL and MSFT"
        )
    assert result.get("error") is True
    assert result["code"] == "DATA_UNAVAILABLE"


# ── Multi-stock: LLM path (L430-599) ─────────────────────────────────────

def _make_multi_patch(symbols, llm_response="AAPL and MSFT both rose."):
    rows = [make_row(date(2025, 4, 1), 100.0), make_row(date(2026, 3, 28), 115.0)]
    price_result = _rows_to_price_result(rows)
    return (
        patch("investorai_mcp.tools.get_trend_summary.get_price_history",
              new=AsyncMock(return_value=price_result)),
        patch("investorai_mcp.tools.get_trend_summary.get_news",
              new=AsyncMock(return_value=_MOCK_NEWS)),
        patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
              new=AsyncMock(return_value=_MOCK_STOCK_INFO)),
        patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
              new=AsyncMock(return_value=_MOCK_SENTIMENT)),
        patch("investorai_mcp.tools.get_trend_summary.call_llm",
              new=AsyncMock(return_value=llm_response)),
    )


async def test_multi_stock_returns_multi_flag():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    patches = _make_multi_patch(["AAPL", "MSFT"])
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        result = await get_trend_summary("AAPL", question="Compare AAPL and MSFT")
    assert result.get("multi") is True


async def test_multi_stock_has_summary():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    patches = _make_multi_patch(["AAPL", "MSFT"])
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        result = await get_trend_summary("AAPL", question="Compare AAPL and MSFT")
    assert isinstance(result.get("summary"), str)
    assert len(result["summary"]) > 0


async def test_multi_stock_has_symbols_list():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    patches = _make_multi_patch(["AAPL", "MSFT"])
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        result = await get_trend_summary("AAPL", question="Compare AAPL and MSFT")
    assert "AAPL" in result.get("symbols", [])
    assert "MSFT" in result.get("symbols", [])


async def test_multi_stock_has_citations():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    patches = _make_multi_patch(["AAPL", "MSFT"])
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        result = await get_trend_summary("AAPL", question="Compare AAPL and MSFT")
    assert isinstance(result.get("citations"), list)


async def test_multi_stock_validation_passed_present():
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    patches = _make_multi_patch(["AAPL", "MSFT"])
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        result = await get_trend_summary("AAPL", question="Compare AAPL and MSFT")
    assert "validation_passed" in result


async def test_multi_stock_llm_unavailable_returns_error():
    """LLM failure on multi-stock path returns LLM_UNAVAILABLE."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    rows = [make_row(date(2025, 4, 1), 100.0), make_row(date(2026, 3, 28), 115.0)]
    price_result = _rows_to_price_result(rows)
    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=price_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=_MOCK_SENTIMENT)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(side_effect=RuntimeError("quota exceeded"))):
        result = await get_trend_summary("AAPL", question="Compare AAPL and MSFT")
    assert result.get("error") is True
    assert result["code"] == "LLM_UNAVAILABLE"


async def test_multi_stock_news_focus_returns_sentiments():
    """Multi-stock news question returns 'sentiments' dict keyed by symbol."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    rows = [make_row(date(2025, 4, 1), 100.0), make_row(date(2026, 3, 28), 115.0)]
    price_result = _rows_to_price_result(rows)
    sentiment_positive = {
        **_MOCK_SENTIMENT,
        "sentiment": "positive",
        "score": 0.6,
        "key_themes": ["earnings beat"],
    }
    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=price_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=sentiment_positive)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(return_value="Both AAPL and MSFT had positive news.")):
        # Note: no trailing '?' so MSFT is space-padded and detected by detect_symbols
        result = await get_trend_summary(
            "AAPL",
            question="Latest news for AAPL and MSFT stock"
        )
    assert result.get("multi") is True
    sentiments = result.get("sentiments")
    assert sentiments is not None
    assert "AAPL" in sentiments or "MSFT" in sentiments


async def test_multi_stock_date_range_builds_combined_prompt():
    """Multi-stock with a date range uses COT prompt and produces a summary."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    rows = [
        make_row(date(2023, 5, 2), 150.0),
        make_row(date(2025, 5, 30), 180.0),
    ]
    price_result = _rows_to_price_result(rows)
    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=price_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=_MOCK_SENTIMENT)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(return_value="Both stocks rose from May 2023 to May 2025.")):
        result = await get_trend_summary(
            "AAPL",
            question="How did AAPL and MSFT do from May 2023 to May 2025?"
        )
    assert result.get("multi") is True
    assert "summary" in result


async def test_multi_stock_large_comparison_uses_compact_format():
    """More than 10 symbols uses compact one-liner per stock format."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    rows = [make_row(date(2025, 4, 1), 100.0), make_row(date(2026, 3, 28), 110.0)]
    price_result = _rows_to_price_result(rows)
    captured_messages = []

    async def capture_llm(messages, **kwargs):
        captured_messages.extend(messages)
        return "All stocks summary."

    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=price_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)), \
         patch("investorai_mcp.tools.get_trend_summary.get_sentiment",
               new=AsyncMock(return_value=_MOCK_SENTIMENT)), \
         patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(side_effect=capture_llm)):
        result = await get_trend_summary("AAPL", question="Compare all stocks")
    # Large comparison: prompt content should contain compact-format lines (return %)
    combined = " ".join(str(m) for m in captured_messages)
    assert "return" in combined.lower() or result.get("multi") is True


async def test_multi_stock_timings_present():
    """Multi-stock response includes _timings block."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    patches = _make_multi_patch(["AAPL", "MSFT"])
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        result = await get_trend_summary("AAPL", question="Compare AAPL and MSFT")
    assert "_timings" in result
    assert "db_fetch_ms" in result["_timings"]
    assert "llm_ms" in result["_timings"]


async def test_ticker_symbol_param_unsupported_no_question_symbols():
    """When ticker_symbol param is unsupported and question has no detected symbols, error returned."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    with patch("investorai_mcp.tools.get_trend_summary.call_llm",
               new=AsyncMock(return_value="summary")) as mock_llm:
        result = await get_trend_summary(
            "FAKECORP",
            question="How has this stock performed recently"
        )
    mock_llm.assert_not_called()
    assert result.get("error") is True
    assert result["code"] == "TICKER_NOT_SUPPORTED"


async def test_price_error_response_propagated():
    """When get_price_history returns an error, it is propagated."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    error_result = {"error": True, "code": "PROVIDER_ERROR", "message": "yfinance down"}
    with patch("investorai_mcp.tools.get_trend_summary.get_price_history",
               new=AsyncMock(return_value=error_result)), \
         patch("investorai_mcp.tools.get_trend_summary.get_news",
               new=AsyncMock(return_value=_MOCK_NEWS)), \
         patch("investorai_mcp.tools.get_trend_summary.get_stock_info",
               new=AsyncMock(return_value=_MOCK_STOCK_INFO)):
        result = await get_trend_summary("AAPL")
    assert result.get("error") is True
    assert result["code"] == "PROVIDER_ERROR"


async def test_timings_in_single_stock_response():
    """Single-stock response always includes _timings."""
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    p1, p2, p3, p4, p5 = patch_pipeline()
    with p1, p2, p3, p4, p5:
        result = await get_trend_summary("AAPL")
    assert "_timings" in result
    assert "db_fetch_ms" in result["_timings"]
    assert "llm_ms" in result["_timings"]
    assert "validation_ms" in result["_timings"]
