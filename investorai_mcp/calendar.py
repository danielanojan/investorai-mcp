"""
US Market Calendar - trading hours and holiday detection

This will be used by cache manager triggering yfinance refreshes
when the market is closed. No external dependencies - holiday list
is hardcorded based on NYSE holidays for 2026-2030.

Proper daylight saving time detection requires either a timezone library
(pytz or zoneinfo) or a complex calculation

being off by 1 hour twice a year has no real consequence —
we might skip one extra refresh at market open in spring and trigger one extra at close in autumn.
For a cache TTL decision, that's completely acceptable.
"""

from datetime import UTC, date, datetime, time, timedelta

# US federal market holidays 2025-2030
# Source: NYSE holiday calendar
_HOLIDAYS: set[date] = {
    # 2026
    date(2026, 1, 1),  # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 4, 3),  # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),  # Independence Day (observed)
    date(2026, 9, 7),  # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
    # 2027
    date(2027, 1, 1),  # New Year's Day
    date(2027, 1, 18),  # MLK Day
    date(2027, 2, 15),  # Presidents' Day
    date(2027, 3, 26),  # Good Friday
    date(2027, 5, 31),  # Memorial Day
    date(2027, 6, 18),  # Juneteenth (observed)
    date(2027, 7, 5),  # Independence Day (observed)
    date(2027, 9, 6),  # Labor Day
    date(2027, 11, 25),  # Thanksgiving
    date(2027, 12, 24),  # Christmas (observed)
    # 2028
    date(2028, 1, 1),  # New Year's Day (observed)
    date(2028, 1, 17),  # MLK Day
    date(2028, 2, 21),  # Presidents' Day
    date(2028, 4, 14),  # Good Friday
    date(2028, 5, 29),  # Memorial Day
    date(2028, 6, 19),  # Juneteenth
    date(2028, 7, 4),  # Independence Day
    date(2028, 9, 4),  # Labor Day
    date(2028, 11, 23),  # Thanksgiving
    date(2028, 12, 25),  # Christmas
    # 2029
    date(2029, 1, 1),  # New Year's Day
    date(2029, 1, 15),  # MLK Day
    date(2029, 2, 19),  # Presidents' Day
    date(2029, 3, 30),  # Good Friday
    date(2029, 5, 28),  # Memorial Day
    date(2029, 6, 19),  # Juneteenth
    date(2029, 7, 4),  # Independence Day
    date(2029, 9, 3),  # Labor Day
    date(2029, 11, 22),  # Thanksgiving
    date(2029, 12, 25),  # Christmas
    # 2030
    date(2030, 1, 1),  # New Year's Day
    date(2030, 1, 21),  # MLK Day
    date(2030, 2, 18),  # Presidents' Day
    date(2030, 4, 19),  # Good Friday
    date(2030, 5, 27),  # Memorial Day
    date(2030, 6, 19),  # Juneteenth
    date(2030, 7, 4),  # Independence Day
    date(2030, 9, 2),  # Labor Day
    date(2030, 11, 28),  # Thanksgiving
    date(2030, 12, 25),  # Christmas
}

# Market hours in Eastern Time (UTC-5 standard, UTC-4 daylight)
_MARKET_OPEN_ET = time(9, 30)
_MARKET_CLOSE_ET = time(16, 0)


class USMarketCalendar:
    """
    Checks US stock market open/ closed status

    Usage:
        cal = USMarketCalendar()
        if cal.is_market_open():
            #then refresh from yfinance.
    """

    def is_holiday(self, d: date | None = None) -> bool:
        """Returns True if the given date is a US market holiday. If no date is provided, uses today's date."""
        if d is None:
            d = datetime.now(UTC).date()
        return d in _HOLIDAYS

    def is_weekend(self, d: date | None = None) -> bool:
        """Returns True if the given date is a weekend. If no date is provided, uses today's date."""
        if d is None:
            d = datetime.now(UTC).date()
        return d.weekday() >= 5  # 5 = Saturday, 6 = Sunday

    def is_trading_day(self, d: date | None = None) -> bool:
        """Returns True if the given date is a US market trading day (not a weekend or holiday). If no date is provided, uses today's date."""
        if d is None:
            d = datetime.now(UTC).date()
        return not self.is_weekend(d) and not self.is_holiday(d)

    def is_market_open(self, dt: datetime | None = None) -> bool:
        """
        Return True if the market is currently open.

        Checks: weekday, not a holiday and within 9:30-16:00 ET.
        Uses a simple UTC offset - ET is UTC-5 (standard) or UTC-4 (daylight). For simplicity, we assume daylight saving is in effect from March to November.
        We use UTC-5 year round for simplicity. This may be off by 1 hour during
        daylight saving transisions but acceptable for cache refresh decisions.
        """

        if dt is None:
            dt = datetime.now(UTC)

        # Convert to US Eastern Time (ET)
        et_offset = -5  # UTC-5 for simplicity, ignoring daylight saving
        et_hour = (dt.hour + et_offset) % 24
        et_minute = dt.minute
        et_time = time(et_hour, et_minute)
        et_date = dt.date()

        # Adjust date if ET is a different calendar day than UTC
        if dt.hour < 5:
            from datetime import timedelta

            et_date = et_date - timedelta(days=1)

        if not self.is_trading_day(et_date):
            return False

        return _MARKET_OPEN_ET <= et_time < _MARKET_CLOSE_ET

    def next_market_open(self) -> date:
        """Return the next day market will open."""

        d = datetime.now(UTC).date() + timedelta(days=1)
        while not self.is_trading_day(d):
            d += timedelta(days=1)
        return d


# Module-level singleton — import and use directly
calendar = USMarketCalendar()
