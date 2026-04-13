""" Test for the post-generation validator."""
from datetime import date


import pytest

from investorai_mcp.llm.prompt_builder import PriceSummaryStats
from investorai_mcp.llm.validator import (
    TOLERANCE_PCT,
    IDK_RESPONSE,
    Violation,
    extract_numbers,
    validate_response,
)

@pytest.fixture
def sample_stats():
    return PriceSummaryStats(
        ticker_symbol="AAPL",
        range="1Y",
        start_date=date(2025, 4, 1),
        end_date=date(2026, 3, 28),
        start_price=150.0,
        end_price=174.32,
        period_return_pct=16.21,
        high_price=182.50,
        high_date=date(2025, 12, 15),
        low_price=142.10,
        low_date=date(2025, 6, 10),
        avg_price=163.45,
        avg_daily_volume=55_000_000,
        volatality_pct=24.3,
        trading_days=252,
    )
    

#----Extract_numbers-----------------------------

def test_extracts_dollar_price():
    assert 174.32 in extract_numbers("AAPL closed at $174.32")

def test_extracts_price_with_comma():
    assert 1234.56 in extract_numbers("priced at $1234.56")

def test_extracts_percentage():
    numbers = extract_numbers("AAPL return was 12.3%")
    assert 12.3 in numbers
    
def test_extracts_negative_pecentage():
    numbers = extract_numbers("down 5.3% this month")
    assert 5.3 in numbers

def test_extracts_plain_decimal():
    numbers = extract_numbers("Average price was 163.45")
    assert 163.45 in numbers
    
def test_does_not_extract_year():
    numbers = extract_numbers("in 2026 the price was $174.32")
    assert 174.32 in numbers
    assert 2026 not in numbers

def test_does_not_extract_single_digits():
    numbers = extract_numbers("only 5 stocks in the portfolio")
    assert 5.0 not in numbers
    
def test_empty_text_returns_empty():
    assert extract_numbers("") == []
    
def test_no_numbers_returns_empty():
    assert extract_numbers("AAPL had a great year") == []
    
def test_extracts_billion():
    numbers = extract_numbers("Company had revenue of 1.2B")
    assert any(n > 1_000_000_000 for n in numbers)
    
def test_deduplicates_in_numbers():
    numbers = extract_numbers("price $174.32 and again $174.32")
    assert numbers.count(174.32) == 1
    
##### Validate responses ------------------------------

def test_valid_response_passes(sample_stats):
    response = (
        "AAPL started at $150.0 [source: DB • 2025-04-01] "
        "and ended at $174.32 [source: DB • 2026-03-28]."
    )
    result = validate_response(response, sample_stats)
    assert result.passed is True
    assert result.response == response
    
def test_hallucinated_number_fails(sample_stats):
    # $999.99 is nowhere near the ground truth value
    response = "AAPL closed at $999.99 this year."
    result = validate_response(response, sample_stats)
    assert result.passed is False
    assert len(result.violations) > 0
    
def test_failed_response_returns_idk(sample_stats):
    response = "AAPL reached $999.99 this year"
    result = validate_response(response, sample_stats)
    assert result.response == IDK_RESPONSE
    
def test_no_numbers_passes(sample_stats):
    response = "AAPL had a great year with strong returns."
    result = validate_response(response, sample_stats)
    assert result.passed is True
    
def test_violation_contains_claimed_and_actual(sample_stats):
    response = "AAPL closed at $999.99 yesterday"
    result = validate_response(response, sample_stats)
    assert result.passed is False
    v = result.violations[0]
    assert isinstance(v.claimed, float)
    assert isinstance(v.actual, float)
    assert isinstance(v.deviation, float)
    
def test_tolerance_boundary_passes(sample_stats):
    # 174.32 * 1.004 = 174.99 - within 0.5% tolerance. 
    close_value = round(sample_stats.end_price * 1.004, 2)
    response = f"AAPL closed at ${close_value}."
    result = validate_response(response, sample_stats)
    assert result.passed is True
    
def test_just_outside_tolerance_fails(sample_stats):
    # 174.32 * 1.01 = 176.06 - just outside 0.5% tolerance. 
    fair_value = round(sample_stats.end_price * 1.01, 2)
    response = f"AAPL closed at ${fair_value}."
    result = validate_response(response, sample_stats)
    assert result.passed is False
    
def test_multiple_valid_numbers_pass(sample_stats):
    response = (
        f"AAPL started at ${sample_stats.start_price:.2f}"
        f"and ended at ${sample_stats.end_price:.2f}"
    )
    result = validate_response(response, sample_stats)
    assert result.passed is True
    
def test_idk_response_text():
    assert len(IDK_RESPONSE) > 0
    assert "reliable data" in IDK_RESPONSE
    


