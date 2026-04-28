"""Tests for investorai_mcp/tools/get_system_info.py — pure sync helper."""


def test_today_question_returns_date_string():
    from investorai_mcp.tools.get_system_info import handle_meta_question

    result = handle_meta_question("what is today's date?")
    assert result is not None
    assert "Today is" in result["summary"]
    assert result["validation_passed"] is True
    assert result["citations"] == []


def test_current_date_phrase():
    from investorai_mcp.tools.get_system_info import handle_meta_question

    result = handle_meta_question("what date is it today")
    assert result is not None
    assert "Today is" in result["summary"]


def test_sectors_question_returns_sector_list():
    from investorai_mcp.tools.get_system_info import handle_meta_question

    result = handle_meta_question("what sectors do you support?")
    assert result is not None
    assert "sector" in result["summary"].lower()
    assert "50" in result["summary"] or "stocks" in result["summary"]


def test_sectors_available_phrase():
    from investorai_mcp.tools.get_system_info import handle_meta_question

    result = handle_meta_question("which sectors are available?")
    assert result is not None
    assert "sector" in result["summary"].lower()


def test_stocks_question_returns_ticker_list():
    from investorai_mcp.tools.get_system_info import handle_meta_question

    result = handle_meta_question("what stocks do you support?")
    assert result is not None
    assert "50" in result["summary"]
    assert "AAPL" in result["summary"] or "Apple" in result["summary"]


def test_tickers_phrase():
    from investorai_mcp.tools.get_system_info import handle_meta_question

    result = handle_meta_question("what tickers can I query?")
    assert result is not None
    assert result["validation_passed"] is True


def test_data_range_question():
    from investorai_mcp.tools.get_system_info import handle_meta_question

    result = handle_meta_question("how far back does your data go?")
    assert result is not None
    assert "5 year" in result["summary"].lower() or "5" in result["summary"]


def test_data_available_phrase():
    from investorai_mcp.tools.get_system_info import handle_meta_question

    result = handle_meta_question("how much data is available?")
    assert result is not None


def test_none_returned_for_price_question():
    from investorai_mcp.tools.get_system_info import handle_meta_question

    assert handle_meta_question("What is AAPL's stock price?") is None


def test_none_returned_for_news_question():
    from investorai_mcp.tools.get_system_info import handle_meta_question

    assert handle_meta_question("latest news about Tesla") is None


def test_performance_question_returns_none_for_sectors():
    from investorai_mcp.tools.get_system_info import handle_meta_question

    # "best" is a performance word — sectors/stocks questions are suppressed
    result = handle_meta_question("what is the best sector?")
    assert result is None


def test_performance_question_returns_none_for_stocks():
    from investorai_mcp.tools.get_system_info import handle_meta_question

    result = handle_meta_question("which stocks have the best return?")
    assert result is None


def test_today_still_works_with_performance_word():
    from investorai_mcp.tools.get_system_info import handle_meta_question

    # "today" check runs before the performance guard
    result = handle_meta_question("what is today's date, best day to invest?")
    assert result is not None
    assert "Today is" in result["summary"]


async def test_get_system_info_matched():
    from investorai_mcp.tools.get_system_info import get_system_info

    result = await get_system_info("what is today's date?")
    assert result["matched"] is True
    assert "Today is" in result["summary"]


async def test_get_system_info_not_matched():
    from investorai_mcp.tools.get_system_info import get_system_info

    result = await get_system_info("What is AAPL stock price?")
    assert result["matched"] is False
    assert len(result) == 1
