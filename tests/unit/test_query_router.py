"""Tests for investorai_mcp/llm/query_router.py"""

import pytest

from investorai_mcp.llm.query_router import QueryType, classify

# ── meta ─────────────────────────────────────────────────────────────────────


def test_meta_what_can_you_do():
    qc = classify("What can you do?")
    assert qc.type == QueryType.META
    assert qc.symbols == ()


def test_meta_which_stocks_supported():
    qc = classify("Which stocks are supported?")
    assert qc.type == QueryType.META


def test_meta_what_stocks_available():
    qc = classify("What stocks are available in your universe?")
    assert qc.type == QueryType.META


def test_meta_capabilities():
    qc = classify("Tell me about your capabilities")
    assert qc.type == QueryType.META


def test_meta_hint_mentions_get_system_info():
    qc = classify("What can you do?")
    assert "get_system_info" in qc.hint


# ── broad ─────────────────────────────────────────────────────────────────────


def test_broad_all_stocks():
    qc = classify("Compare all stocks by performance this year")
    assert qc.type == QueryType.BROAD


def test_broad_by_sector():
    qc = classify("Which sector performed best in 2024?")
    assert qc.type == QueryType.BROAD


def test_broad_rank_all():
    qc = classify("Rank all stocks by return over the last year")
    assert qc.type == QueryType.BROAD


def test_broad_hint_mentions_batch():
    qc = classify("Compare all stocks this year")
    assert "batch" in qc.hint.lower()


# ── single stock ──────────────────────────────────────────────────────────────


def test_single_stock_detected():
    qc = classify("How is AAPL doing this year?")
    assert qc.type == QueryType.SINGLE_STOCK
    assert qc.symbols == ("AAPL",)


def test_single_stock_hint_mentions_symbol():
    qc = classify("What's the trend for MSFT?")
    assert "MSFT" in qc.hint


def test_single_stock_no_batch():
    qc = classify("Tell me about GOOGL's recent news")
    assert "non-batch" in qc.hint or "targeted" in qc.hint


# ── multi stock ───────────────────────────────────────────────────────────────


def test_multi_stock_two_symbols():
    qc = classify("Compare AAPL vs MSFT over the last year")
    assert qc.type == QueryType.MULTI_STOCK
    assert "AAPL" in qc.symbols
    assert "MSFT" in qc.symbols


def test_multi_stock_three_symbols():
    qc = classify("How do AAPL, MSFT, and GOOGL compare in 2024?")
    assert qc.type == QueryType.MULTI_STOCK
    assert len(qc.symbols) == 3


def test_multi_stock_caps_at_nine():
    # Construct a question with 12 known symbols
    symbols = [
        "AAPL",
        "MSFT",
        "GOOGL",
        "AMZN",
        "META",
        "NVDA",
        "JPM",
        "BAC",
        "WFC",
        "JNJ",
        "PFE",
        "V",
    ]
    question = "Compare " + " ".join(symbols)
    qc = classify(question)
    assert qc.type == QueryType.MULTI_STOCK
    assert len(qc.symbols) <= 9


def test_multi_stock_hint_lists_symbols():
    qc = classify("AAPL and MSFT performance comparison")
    assert "AAPL" in qc.hint
    assert "MSFT" in qc.hint


# ── no symbol detected ────────────────────────────────────────────────────────


def test_no_symbol_falls_back_to_single():
    qc = classify("How is Apple doing?")
    assert qc.type == QueryType.SINGLE_STOCK
    assert qc.symbols == ()


def test_no_symbol_hint_mentions_parse_question():
    qc = classify("Tell me about the biggest tech company")
    assert "parse_question" in qc.hint


# ── deduplication ─────────────────────────────────────────────────────────────


def test_duplicate_symbols_deduplicated():
    qc = classify("Is AAPL better than AAPL?")
    assert qc.type == QueryType.SINGLE_STOCK
    assert qc.symbols.count("AAPL") == 1


# ── QueryClass is frozen ──────────────────────────────────────────────────────


def test_query_class_is_immutable():
    qc = classify("How is AAPL doing?")
    with pytest.raises((AttributeError, TypeError)):
        qc.type = QueryType.META  # type: ignore[misc]
