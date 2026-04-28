"""Tests for investorai_mcp/tools/parse_question.py — pure sync helpers + async wrapper."""

from datetime import date, timedelta

# ── detect_range ─────────────────────────────────────────────────────────────


def test_detect_range_5y():
    from investorai_mcp.tools.parse_question import detect_range

    assert detect_range("show me 5 year performance") == "5Y"
    assert detect_range("past 5 years") == "5Y"
    assert detect_range("five-year chart") == "5Y"
    assert detect_range("5yr trend") == "5Y"


def test_detect_range_3y():
    from investorai_mcp.tools.parse_question import detect_range

    assert detect_range("last 3 years") == "3Y"
    assert detect_range("three-year data") == "3Y"
    assert detect_range("3yr return") == "3Y"


def test_detect_range_1y():
    from investorai_mcp.tools.parse_question import detect_range

    assert detect_range("past year performance") == "1Y"
    assert detect_range("this year") == "1Y"
    assert detect_range("last year") == "1Y"
    assert detect_range("12 month return") == "1Y"
    assert detect_range("one year trend") == "1Y"


def test_detect_range_6m():
    from investorai_mcp.tools.parse_question import detect_range

    assert detect_range("last 6 months") == "6M"
    assert detect_range("six month chart") == "6M"
    assert detect_range("half year data") == "6M"


def test_detect_range_3m():
    from investorai_mcp.tools.parse_question import detect_range

    assert detect_range("last quarter") == "3M"
    assert detect_range("3 month performance") == "3M"
    assert detect_range("three months") == "3M"
    assert detect_range("last 3 months") == "3M"


def test_detect_range_1m():
    from investorai_mcp.tools.parse_question import detect_range

    assert detect_range("last month") == "1M"
    assert detect_range("30 day chart") == "1M"
    assert detect_range("one month trend") == "1M"
    assert detect_range("past month") == "1M"


def test_detect_range_1w():
    from investorai_mcp.tools.parse_question import detect_range

    assert detect_range("this week") == "1W"
    assert detect_range("last week performance") == "1W"
    assert detect_range("7 day chart") == "1W"
    assert detect_range("one-week data") == "1W"


def test_detect_range_none():
    from investorai_mcp.tools.parse_question import detect_range

    assert detect_range("how is AAPL doing?") is None
    assert detect_range("latest news") is None


# ── detect_symbols ────────────────────────────────────────────────────────────


def test_detect_symbols_explicit_ticker():
    from investorai_mcp.tools.parse_question import detect_symbols

    result = detect_symbols("What is AAPL doing today?")
    assert "AAPL" in result


def test_detect_symbols_multiple_tickers():
    from investorai_mcp.tools.parse_question import detect_symbols

    result = detect_symbols("Compare AAPL and MSFT performance")
    assert "AAPL" in result
    assert "MSFT" in result


def test_detect_symbols_company_name():
    from investorai_mcp.tools.parse_question import detect_symbols

    result = detect_symbols("How is Apple performing this year?")
    assert "AAPL" in result


def test_detect_symbols_no_match():
    from investorai_mcp.tools.parse_question import detect_symbols

    result = detect_symbols("What is the weather today?")
    assert result == []


def test_detect_symbols_ticker_at_start():
    from investorai_mcp.tools.parse_question import detect_symbols

    result = detect_symbols("TSLA had a great quarter")
    assert "TSLA" in result


def test_detect_symbols_ticker_at_end():
    from investorai_mcp.tools.parse_question import detect_symbols

    result = detect_symbols("Show me the chart for NVDA")
    assert "NVDA" in result


# ── detect_sector ─────────────────────────────────────────────────────────────


def test_detect_sector_technology():
    from investorai_mcp.tools.parse_question import detect_sector

    tickers, sectors = detect_sector("how is the tech sector doing?")
    assert len(tickers) > 0
    assert "Technology" in sectors


def test_detect_sector_energy():
    from investorai_mcp.tools.parse_question import detect_sector

    tickers, sectors = detect_sector("show me energy stocks")
    assert len(tickers) > 0
    assert "Energy & Industrials" in sectors


def test_detect_sector_finance():
    from investorai_mcp.tools.parse_question import detect_sector

    tickers, sectors = detect_sector("how are banking stocks performing?")
    assert len(tickers) > 0
    assert "Finance" in sectors


def test_detect_sector_healthcare():
    from investorai_mcp.tools.parse_question import detect_sector

    tickers, sectors = detect_sector("what about healthcare stocks?")
    assert len(tickers) > 0
    assert "Healthcare" in sectors


def test_detect_sector_no_match():
    from investorai_mcp.tools.parse_question import detect_sector

    tickers, sectors = detect_sector("how is AAPL doing?")
    assert tickers == []
    assert sectors == []


# ── is_all_stocks_question ────────────────────────────────────────────────────


def test_is_all_stocks_question_true():
    from investorai_mcp.tools.parse_question import is_all_stocks_question

    assert is_all_stocks_question("show me all stocks") is True
    assert is_all_stocks_question("rank all 50 tickers") is True
    assert is_all_stocks_question("best performing stock this year") is True
    assert is_all_stocks_question("compare all tickers") is True


def test_is_all_stocks_question_false():
    from investorai_mcp.tools.parse_question import is_all_stocks_question

    assert is_all_stocks_question("how is AAPL doing?") is False
    assert is_all_stocks_question("tech sector performance") is False


# ── is_news_question ──────────────────────────────────────────────────────────


def test_is_news_question_true():
    from investorai_mcp.tools.parse_question import is_news_question

    assert is_news_question("latest news about AAPL") is True
    assert is_news_question("any headlines for Tesla?") is True
    assert is_news_question("what is NVDA saying?") is True


def test_is_news_question_false():
    from investorai_mcp.tools.parse_question import is_news_question

    assert is_news_question("show me AAPL price history") is False
    assert is_news_question("how is MSFT performing?") is False


# ── resolve_relative_date ─────────────────────────────────────────────────────


def test_resolve_relative_date_today():
    from datetime import UTC, datetime

    from investorai_mcp.tools.parse_question import resolve_relative_date

    result = resolve_relative_date("what happened today?")
    assert result == datetime.now(UTC).date()


def test_resolve_relative_date_yesterday():
    from datetime import UTC, datetime

    from investorai_mcp.tools.parse_question import resolve_relative_date

    today = datetime.now(UTC).date()
    result = resolve_relative_date("what happened yesterday?")
    assert result == today - timedelta(days=1)


def test_resolve_relative_date_days_ago():
    from datetime import UTC, datetime

    from investorai_mcp.tools.parse_question import resolve_relative_date

    today = datetime.now(UTC).date()
    result = resolve_relative_date("3 days ago what was the price?")
    assert result == today - timedelta(days=3)


def test_resolve_relative_date_weeks_ago():
    from datetime import UTC, datetime

    from investorai_mcp.tools.parse_question import resolve_relative_date

    today = datetime.now(UTC).date()
    result = resolve_relative_date("a week ago")
    assert result == today - timedelta(days=7)


def test_resolve_relative_date_last_weekday():
    from investorai_mcp.tools.parse_question import resolve_relative_date

    result = resolve_relative_date("last Monday what was AAPL?")
    assert result is not None
    assert result.weekday() == 0  # Monday


def test_resolve_relative_date_same_weekday_returns_7_days_ago():
    from datetime import UTC, datetime

    from investorai_mcp.tools.parse_question import resolve_relative_date

    today = datetime.now(UTC).date()
    weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    today_name = weekday_names[today.weekday()]
    result = resolve_relative_date(f"last {today_name} price")
    assert result == today - timedelta(days=7)


def test_resolve_relative_date_none():
    from investorai_mcp.tools.parse_question import resolve_relative_date

    assert resolve_relative_date("show me the last year") is None
    assert resolve_relative_date("how is AAPL doing?") is None


# ── resolve_absolute_date ─────────────────────────────────────────────────────


def test_resolve_absolute_date_month_day_year():
    from investorai_mcp.tools.parse_question import resolve_absolute_date

    result = resolve_absolute_date("on May 12, 2020")
    assert result == date(2020, 5, 12)


def test_resolve_absolute_date_day_month_year():
    from investorai_mcp.tools.parse_question import resolve_absolute_date

    result = resolve_absolute_date("on 12 May 2020")
    assert result == date(2020, 5, 12)


def test_resolve_absolute_date_iso_format():
    from investorai_mcp.tools.parse_question import resolve_absolute_date

    result = resolve_absolute_date("price on 2020-05-12")
    assert result == date(2020, 5, 12)


def test_resolve_absolute_date_slash_format():
    from investorai_mcp.tools.parse_question import resolve_absolute_date

    result = resolve_absolute_date("what about 2020/05/12?")
    assert result == date(2020, 5, 12)


def test_resolve_absolute_date_none():
    from investorai_mcp.tools.parse_question import resolve_absolute_date

    assert resolve_absolute_date("how is AAPL doing this year?") is None


def test_resolve_absolute_date_invalid_feb31_month_first():
    from investorai_mcp.tools.parse_question import resolve_absolute_date

    assert resolve_absolute_date("on Feb 31, 2023") is None


def test_resolve_absolute_date_invalid_feb31_day_first():
    from investorai_mcp.tools.parse_question import resolve_absolute_date

    assert resolve_absolute_date("on 31 Feb 2023") is None


def test_resolve_absolute_date_invalid_iso():
    from investorai_mcp.tools.parse_question import resolve_absolute_date

    assert resolve_absolute_date("price on 2023-02-31") is None


# ── detect_duration ───────────────────────────────────────────────────────────


def test_detect_duration_days():
    from datetime import UTC, datetime

    from investorai_mcp.tools.parse_question import detect_duration

    today = datetime.now(UTC).date()
    result = detect_duration("last 30 days")
    assert result is not None
    start, end = result
    assert end == today
    assert start == today - timedelta(days=30)


def test_detect_duration_weeks():
    from investorai_mcp.tools.parse_question import detect_duration

    result = detect_duration("past 2 weeks")
    assert result is not None
    start, end = result
    assert (end - start).days == 14


def test_detect_duration_months():
    from investorai_mcp.tools.parse_question import detect_duration

    result = detect_duration("last 3 months")
    assert result is not None


def test_detect_duration_years():
    from investorai_mcp.tools.parse_question import detect_duration

    result = detect_duration("past 2 years")
    assert result is not None
    start, end = result
    assert (end - start).days > 700


def test_detect_duration_none():
    from investorai_mcp.tools.parse_question import detect_duration

    assert detect_duration("show me this year") is None
    assert detect_duration("last year") is None


# ── resolve_date_range ────────────────────────────────────────────────────────


def test_resolve_date_range_month_year():
    from investorai_mcp.tools.parse_question import resolve_date_range

    result = resolve_date_range("from May 2023 to May 2025")
    assert result is not None
    start, end = result
    assert start.year == 2023
    assert start.month == 5
    assert end.year == 2025
    assert end.month == 5


def test_resolve_date_range_iso():
    from investorai_mcp.tools.parse_question import resolve_date_range

    result = resolve_date_range("2023-01-01 to 2024-12-31")
    assert result is not None
    start, end = result
    assert start == date(2023, 1, 1)
    assert end == date(2024, 12, 31)


def test_resolve_date_range_none():
    from investorai_mcp.tools.parse_question import resolve_date_range

    assert resolve_date_range("how is AAPL doing?") is None


def test_resolve_date_range_invalid_iso_start():
    from investorai_mcp.tools.parse_question import resolve_date_range

    assert resolve_date_range("2023-02-30 to 2024-12-31") is None


def test_resolve_date_range_full_dates():
    from investorai_mcp.tools.parse_question import resolve_date_range

    result = resolve_date_range("from May 12, 2023 to December 14, 2025")
    assert result is not None
    start, end = result
    assert start == date(2023, 5, 12)
    assert end == date(2025, 12, 14)


# ── range_for_date ────────────────────────────────────────────────────────────


def test_range_for_date_1w():
    from datetime import UTC, datetime

    from investorai_mcp.tools.parse_question import range_for_date

    today = datetime.now(UTC).date()
    assert range_for_date(today - timedelta(days=3)) == "1W"


def test_range_for_date_1m():
    from datetime import UTC, datetime

    from investorai_mcp.tools.parse_question import range_for_date

    today = datetime.now(UTC).date()
    assert range_for_date(today - timedelta(days=20)) == "1M"


def test_range_for_date_3m():
    from datetime import UTC, datetime

    from investorai_mcp.tools.parse_question import range_for_date

    today = datetime.now(UTC).date()
    assert range_for_date(today - timedelta(days=60)) == "3M"


def test_range_for_date_6m():
    from datetime import UTC, datetime

    from investorai_mcp.tools.parse_question import range_for_date

    today = datetime.now(UTC).date()
    assert range_for_date(today - timedelta(days=120)) == "6M"


def test_range_for_date_1y():
    from datetime import UTC, datetime

    from investorai_mcp.tools.parse_question import range_for_date

    today = datetime.now(UTC).date()
    assert range_for_date(today - timedelta(days=300)) == "1Y"


def test_range_for_date_3y():
    from datetime import UTC, datetime

    from investorai_mcp.tools.parse_question import range_for_date

    today = datetime.now(UTC).date()
    assert range_for_date(today - timedelta(days=800)) == "3Y"


def test_range_for_date_5y():
    from datetime import UTC, datetime

    from investorai_mcp.tools.parse_question import range_for_date

    today = datetime.now(UTC).date()
    assert range_for_date(today - timedelta(days=1500)) == "5Y"


# ── extract_date_context ──────────────────────────────────────────────────────


def test_extract_date_context_two_years():
    from investorai_mcp.tools.parse_question import extract_date_context

    result = extract_date_context("from 2022 to 2024")
    assert result is not None
    assert "2022" in result
    assert "2024" in result


def test_extract_date_context_single_year():
    from investorai_mcp.tools.parse_question import extract_date_context

    result = extract_date_context("what happened in 2023?")
    assert result is not None
    assert "2023" in result


def test_extract_date_context_none():
    from investorai_mcp.tools.parse_question import extract_date_context

    assert extract_date_context("how is AAPL doing?") is None


# ── parse_question async wrapper ──────────────────────────────────────────────


async def test_parse_question_with_symbol_and_range():
    from investorai_mcp.tools.parse_question import parse_question

    result = await parse_question("How has AAPL performed over the last year?")
    assert "AAPL" in result["symbols"]
    assert result["range"] == "1Y"
    assert result["is_news"] is False
    assert "today" in result


async def test_parse_question_all_stocks():
    from investorai_mcp.tools.parse_question import parse_question

    result = await parse_question("Show me the best performing stocks")
    assert result["is_all_stocks"] is True
    assert len(result["symbols"]) == 50


async def test_parse_question_sector():
    from investorai_mcp.tools.parse_question import parse_question

    result = await parse_question("How is the tech sector doing?")
    assert result["sector_label"] is not None
    assert "Technology" in result["sector_label"]
    assert len(result["symbols"]) > 0


async def test_parse_question_news():
    from investorai_mcp.tools.parse_question import parse_question

    result = await parse_question("TSLA news today")
    assert "TSLA" in result["symbols"]
    assert result["is_news"] is True


async def test_parse_question_with_date():
    from investorai_mcp.tools.parse_question import parse_question

    result = await parse_question("What was AAPL price on 2023-06-15?")
    assert "AAPL" in result["symbols"]
    assert result["resolved_date"] == "2023-06-15"


async def test_parse_question_no_symbol_no_sector():
    from investorai_mcp.tools.parse_question import parse_question

    result = await parse_question("What is the stock market doing?")
    assert isinstance(result["symbols"], list)
    assert result["today"] is not None


async def test_parse_question_with_date_range():
    from investorai_mcp.tools.parse_question import parse_question

    result = await parse_question("AAPL from 2023-01-01 to 2024-06-01")
    assert "AAPL" in result["symbols"]
    assert result["date_range"] is not None
    assert result["date_range"][0] == "2023-01-01"
    assert result["range"] is not None
