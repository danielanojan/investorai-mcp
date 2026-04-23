"""Test for US market calendar"""

from datetime import UTC, date, datetime

import pytest

from investorai_mcp.calendar import USMarketCalendar


@pytest.fixture
def cal():
    return USMarketCalendar()


# ----------Holiday Detection Tests----------


def test_christmas_2026_is_holiday(cal):
    assert cal.is_holiday(date(2026, 12, 25)) is True


def test_thanksgiving_2027_is_holiday(cal):
    assert cal.is_holiday(date(2027, 11, 25)) is True


def test_regular_weekday_is_not_holiday(cal):
    assert cal.is_holiday(date(2026, 3, 26)) is False


def test_new_year_2028_is_holiday(cal):
    assert cal.is_holiday(date(2028, 1, 1)) is True


# ----------weekend detection----------
def test_saturday_is_weekend(cal):
    assert cal.is_weekend(date(2026, 3, 28)) is True


def test_sunday_is_weekend(cal):
    assert cal.is_weekend(date(2026, 3, 29)) is True


def test_weekday_is_not_weekend(cal):
    assert cal.is_weekend(date(2026, 3, 26)) is False


# Trading day --------------------------


def test_regular_monday_is_trading_day(cal):
    assert cal.is_trading_day(date(2026, 3, 23)) is True


def test_saturday_is_not_trading_day(cal):
    assert cal.is_trading_day(date(2026, 3, 28)) is False


def test_christmas_is_not_trading_day(cal):
    assert cal.is_trading_day(date(2026, 12, 25)) is False


def test_good_friday_is_not_trading_day(cal):
    assert cal.is_trading_day(date(2026, 4, 3)) is False


## -- Market open -----------------------
def test_market_open_during_trading_hours(cal):
    # Monday 14:30 UTC is 9:30 ET - market open
    dt = datetime(2026, 3, 23, 14, 30, 0, tzinfo=UTC)
    assert cal.is_market_open(dt) is True


def test_market_closed_before_open(cal):
    # Monday 13:30 UTC is 8:30 ET - market closed
    dt = datetime(2026, 3, 23, 13, 30, 0, tzinfo=UTC)
    assert cal.is_market_open(dt) is False


def test_market_closed_after_close(cal):
    # Monday 21:00 UTC is 16:00 ET - market closed
    dt = datetime(2026, 3, 23, 21, 0, 0, tzinfo=UTC)
    assert cal.is_market_open(dt) is False


def test_market_closed_on_weekend(cal):
    # Saturday 14:30 UTC is 9:30 ET - but market closed on Saturday
    dt = datetime(2026, 3, 28, 14, 30, 0, tzinfo=UTC)
    assert cal.is_market_open(dt) is False


def test_market_closed_on_holiday(cal):
    # Christmas 2026 - market closed all day
    dt = datetime(2026, 12, 25, 14, 30, 0, tzinfo=UTC)
    assert cal.is_market_open(dt) is False


# Next Market Open -----------------------


def test_next_market_open_skips_weekend(cal):
    # if today is Friday, next open should be Monday
    from unittest.mock import patch

    with patch("investorai_mcp.calendar.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 4, 3, 20, 0, 0, tzinfo=UTC)
        next_open = cal.next_market_open()
    # should skip good friday + weekend --> Monday April 6th
    assert next_open == date(2026, 4, 6)
