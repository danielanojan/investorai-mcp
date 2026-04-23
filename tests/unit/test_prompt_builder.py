"""Test for the prompt builder."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from investorai_mcp.db.models import PriceHistory
from investorai_mcp.llm.prompt_builder import (
    SYSTEM_PROMPT,
    PriceSummaryStats,
    build_prompt,
    compute_stats,
)


def make_row(d: date, price: float, volume: int = 1_000_000):
    row = MagicMock(spec=PriceHistory)
    row.date = d
    row.adj_close = price
    row.volume = volume
    return row


@pytest.fixture
def sample_rows():
    return [
        make_row(date(2026, 1, 1), price=150.0, volume=40_000_000),
        make_row(date(2026, 2, 1), price=160.0, volume=50_000_000),
        make_row(date(2026, 3, 1), price=155.0, volume=45_000_000),
        make_row(date(2026, 3, 15), price=180.0, volume=60_000_000),  # high
        make_row(date(2026, 3, 28), price=170.0, volume=55_000_000),
    ]


@pytest.fixture
def sample_stats(sample_rows):
    return compute_stats("AAPL", "1Y", sample_rows)


# ---- Compute Stats ----------------------------------


def test_compute_stats_returns_none_for_empty_rows():
    assert compute_stats("AAPL", "1Y", []) is None


def test_compute_stats_returns_price_summary(sample_stats):
    assert isinstance(sample_stats, PriceSummaryStats)


def test_compute_stats_start_end_price(sample_stats):
    assert sample_stats.start_price == 150.0
    assert sample_stats.end_price == 170.0


def test_compute_stats_period_return(sample_stats):
    expected = round((170.0 - 150.0) / 150.0 * 100, 2)
    assert sample_stats.period_return_pct == expected


def test_compute_stats_high_low(sample_stats):
    assert sample_stats.high_price == 180.0
    assert sample_stats.low_price == 150.0


def test_compute_stats_trading_days(sample_stats, sample_rows):
    assert sample_stats.trading_days == len(sample_rows)


def test_compute_stats_volatality_non_negative(sample_stats):
    assert sample_stats.volatility_pct >= 0


def test_compute_stats_single_row():
    rows = [make_row(date(2026, 3, 28), price=174.0)]
    stats = compute_stats("AAPL", "1D", rows)
    assert stats is not None
    assert stats.volatility_pct == 0.0  # can't compute with 1 row


#### --- PriceSummaryStats.to_text


def test_to_text_contains_ticker(sample_stats):
    text = sample_stats.to_text()
    assert "AAPL" in text


def test_to_text_contains_prices(sample_stats):
    text = sample_stats.to_text()
    assert "150.0" in text
    assert "170.0" in text


def test_to_text_contains_return(sample_stats):
    text = sample_stats.to_text()
    assert "%" in text


def test_to_text_under_200_tokens(sample_stats):
    text = sample_stats.to_text()
    tokens = len(text) // 4
    assert tokens < 200


# ------ Build Prompt ----------------------------------


def test_build_prompt_first_message_is_system(sample_stats):
    messages = build_prompt(sample_stats, "How is AAPL doing?")
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == SYSTEM_PROMPT


def test_build_prompt_contains_question(sample_stats):
    messages = build_prompt(sample_stats, "How is AAPL doing?")
    assert messages[-1]["role"] == "user"


def test_build_prompt_question_in_content(sample_stats):
    question = "What was AAPL's 52-week high?"
    messages = build_prompt(sample_stats, question)
    last = messages[-1]["content"]
    assert question in last


def test_build_prompt_contains_stock_data(sample_stats):
    messages = build_prompt(sample_stats, "How is AAPL?")
    # should be in system prompt or user question.
    user_content = messages[-1]["content"]
    assert "AAPL" in user_content
    assert "DATA_PROVIDED" in user_content


def test_build_prompt_no_row_ohlcv(sample_stats):
    """Raw OHLCV field names must never appear in the prompt."""
    messages = build_prompt(sample_stats, "How is AAPL?")
    full_text = " ".join(m["content"] for m in messages)
    assert "adj_close" not in full_text
    assert "open" not in full_text.lower().split()


def test_build_prompt_with_news(sample_stats):
    history = [
        {"role": "user", "content": "Tell me about AAPL"},
        {"role": "assistant", "content": "AAPL is a tech stock"},
    ]
    messages = build_prompt(sample_stats, "What is the 52-week high?", history=history)
    # system + 2 history + 1 user = 4
    assert len(messages) == 4


def test_build_prompt_news_news(sample_stats):
    news = [MagicMock()]
    news[0].headline = "AAPL beats earnings"
    news[0].source = "Reuters"
    news[0].url = "http://reuters.com/apple"

    messages = build_prompt(sample_stats, "Any news on AAPL?", news=news)
    user_content = messages[-1]["content"]
    assert "RECENT NEWS" in user_content
    assert "AAPL beats earnings" in user_content


def test_build_prompt_with_history(sample_stats):
    """Only first 10 articles should appear."""
    news = [MagicMock() for _ in range(12)]
    for i, n in enumerate(news):
        n.headline = f"headline {i}"
        n.source = "Source"
        n.url = f"http://news.com/article{i}"

    messages = build_prompt(sample_stats, "Any news?", news=news)
    user_content = messages[-1]["content"]

    # Headlines 0-9 should be included, 10-11 should be ignored.
    assert "headline 9" in user_content
    assert "headline 10" not in user_content
