"""Tests for investorai_mcp/api/sanitize.py"""

import pytest

from investorai_mcp.api.sanitize import (
    ALLOWED_MODELS,
    MAX_QUESTION_LEN,
    validate_model,
    validate_question,
    validate_symbol,
)


# ---------------------------------------------------------------------------
# validate_symbol
# ---------------------------------------------------------------------------


def test_valid_symbols():
    assert validate_symbol("aapl") == "AAPL"
    assert validate_symbol("MSFT") == "MSFT"
    assert validate_symbol("BRK-B") == "BRK-B"
    assert validate_symbol("V") == "V"
    assert validate_symbol("  nvda  ") == "NVDA"


def test_invalid_symbol_too_long():
    with pytest.raises(ValueError):
        validate_symbol("TOOLONG")


def test_invalid_symbol_digits():
    with pytest.raises(ValueError):
        validate_symbol("AAP1")


def test_invalid_symbol_sql_injection():
    with pytest.raises(ValueError):
        validate_symbol("'; DROP TABLE prices; --")


def test_invalid_symbol_empty():
    with pytest.raises(ValueError):
        validate_symbol("")


def test_invalid_symbol_special_chars():
    with pytest.raises(ValueError):
        validate_symbol("AA<script>")


# ---------------------------------------------------------------------------
# validate_question
# ---------------------------------------------------------------------------


def test_valid_question():
    assert validate_question("How is AAPL doing?") == "How is AAPL doing?"


def test_question_stripped():
    assert validate_question("  hi  ") == "hi"


def test_question_too_long():
    with pytest.raises(ValueError):
        validate_question("x" * (MAX_QUESTION_LEN + 1))


def test_question_at_max_length():
    q = "x" * MAX_QUESTION_LEN
    assert validate_question(q) == q


# ---------------------------------------------------------------------------
# validate_model
# ---------------------------------------------------------------------------


def test_valid_model():
    assert validate_model("claude-sonnet-4-20250514") == "claude-sonnet-4-20250514"
    assert validate_model("gpt-4o") == "gpt-4o"


def test_invalid_model_unknown():
    with pytest.raises(ValueError):
        validate_model("gpt-99-ultra")


def test_invalid_model_injection():
    with pytest.raises(ValueError):
        validate_model("'; DROP TABLE llm_usage_log; --")


def test_allowed_models_is_non_empty():
    assert len(ALLOWED_MODELS) > 0
