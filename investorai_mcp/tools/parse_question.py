"""
parse_question MCP tool.

Parses a natural language question and returns structured intent:
stock symbols, time range, resolved date, date range, sector, and
question type (news vs. price).

All parsing logic lives here as plain synchronous functions so they
can be imported and unit-tested directly.  The MCP tool wrapper
(`parse_question`) is async and calls the sync helpers, making the
result available to any MCP client that wants to inspect question
understanding before fetching data.
"""
import re
from datetime import date, datetime, timezone

from investorai_mcp.server import mcp
from investorai_mcp.stocks import SUPPORTED_TICKERS

# ── Sector keyword map ────────────────────────────────────────────────────

SECTOR_KEYWORDS: dict[str, list[str]] = {
    "Energy & Industrials": [
        "energy", "oil", "gas", "industrial", "aerospace", "defense",
        "utilities", "solar", "renewable", "refinery",
    ],
    "Technology": [
        "tech", "technology", "software", "semiconductor", "chip",
        "cloud", "ai sector", "internet sector",
    ],
    "Finance": [
        "financ", "bank", "banking", "insurance", "investment",
        "fintech", "payment sector", "wall street",
    ],
    "Healthcare": [
        "health", "healthcare", "pharma", "pharmaceutical", "biotech",
        "medical", "drug sector",
    ],
    "Consumer": [
        "consumer", "retail sector", "restaurant sector",
        "e-commerce sector",
    ],
}

# ── All-stocks phrase list ────────────────────────────────────────────────

ALL_STOCKS_PHRASES = [
    "all 50", "all fifty", "all stocks", "all tickers", "all supported",
    "all the stocks", "all of them", "across all", "universe of",
    "entire universe", "full universe", "whole universe",
    "compare all", "compare stocks", "compare the stocks",
    "rank stocks", "rank the stocks", "ranking stocks",
    "best performing stock", "worst performing stock",
    "best performing", "worst performing",
    "top performing", "bottom performing",
    "best stock", "worst stock",
    "top stock", "top stocks",
    "every stock", "every ticker",
]

# ── News keyword list ─────────────────────────────────────────────────────

NEWS_KEYWORDS = [
    "news", "headline", "article", "latest", "recent news",
    "what's happening", "what is happening", "announcement",
    "update", "say", "saying", "report",
]


# ── Pure sync helpers (importable and unit-testable) ─────────────────────

def detect_range(question: str) -> str | None:
    """Detect a time range shortcode from natural language.  Returns None if no range is detected."""
    q = question.lower()
    if any(w in q for w in [
        "5 year", "5year", "5-year", "5 years", "five year", "five years",
        "five-year", "5yr", "5 yr", "past 5", "last 5 year",
    ]):
        return "5Y"
    if any(w in q for w in [
        "3 year", "3year", "3-year", "3 years", "three year", "three years",
        "three-year", "3yr", "3 yr", "past 3", "last 3 year",
    ]):
        return "3Y"
    if any(w in q for w in [
        "1 year", "1year", "1-year", "1 years", "one year", "one-year",
        "this year", "past year", "last year", "12 month",
        "1yr", "1 yr", "last yr", "past yr", "this yr",
    ]):
        return "1Y"
    if any(w in q for w in [
        "6 month", "6month", "6-month", "six month", "six months",
        "half year", "half-year", "last 6",
    ]):
        return "6M"
    if any(w in q for w in [
        "3 month", "3month", "3-month", "three month", "three months",
        "three-month", "quarter", "last 3 month", "last 3 months",
        "past 3 month", "past quarter", "last 3m", "in 3m", "past 3m",
    ]):
        return "3M"
    if any(w in q for w in [
        "1 month", "1month", "1-month", "one month", "one-month",
        "30 day", "4 week", "5 week", "last month", "past month",
    ]):
        return "1M"
    if any(w in q for w in [
        "1 week", "1week", "1-week", "one week", "one-week",
        "7 day", "this week", "last week",
    ]):
        return "1W"
    return None


def detect_symbols(question: str) -> list[str]:
    """Return all supported ticker symbols mentioned in the question.

    Checks exact ticker matches first, then the first word of each
    company name (must be longer than 3 characters).
    """
    found: list[str] = []
    q_upper = question.upper()
    q_lower = question.lower()

    for symbol in SUPPORTED_TICKERS:
        if (
            f" {symbol} " in f" {q_upper} "
            or q_upper.startswith(f"{symbol} ")
            or q_upper.endswith(f" {symbol}")
        ):
            if symbol not in found:
                found.append(symbol)

    for symbol, info in SUPPORTED_TICKERS.items():
        if symbol in found:
            continue
        raw_first = info["name"].lower().split()[0]
        m = re.match(r'[a-z]+', raw_first)
        first_word = m.group() if m else raw_first
        if len(first_word) > 3 and first_word in q_lower:
            found.append(symbol)

    return found


def detect_sector(question: str) -> tuple[list[str], list[str]]:
    """Detect all sectors mentioned in the question.

    Returns (tickers, matched_sector_names).  All tickers from every
    matched sector are included.  Returns ([], []) when no sector is
    recognised.
    """
    q = question.lower()
    tickers: list[str] = []
    matched_sectors: list[str] = []
    for sector, keywords in SECTOR_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            for sym, info in SUPPORTED_TICKERS.items():
                if info["sector"] == sector and sym not in tickers:
                    tickers.append(sym)
            matched_sectors.append(sector)
    return tickers, matched_sectors


def is_all_stocks_question(question: str) -> bool:
    """Return True if the question asks about the entire supported universe."""
    q = question.lower()
    return any(phrase in q for phrase in ALL_STOCKS_PHRASES)


def is_news_question(question: str) -> bool:
    """Return True if the question is about news or headlines."""
    q = question.lower()
    return any(kw in q for kw in NEWS_KEYWORDS)


def resolve_relative_date(question: str) -> date | None:
    """Resolve a relative date reference to an absolute date.

    Handles: "today", "yesterday", "last Wednesday", "a week ago", "3 days ago".
    Returns None if no relative date reference is found.
    """
    from datetime import timedelta as _td

    _WEEKDAYS = {
        "monday": 0, "mon": 0,
        "tuesday": 1, "tue": 1, "tues": 1,
        "wednesday": 2, "wed": 2,
        "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
        "friday": 4, "fri": 4,
        "saturday": 5, "sat": 5,
        "sunday": 6, "sun": 6,
    }
    q = question.lower()
    today = datetime.now(timezone.utc).date()

    if re.search(r'\btoday\b', q):
        return today
    if re.search(r'\byesterday\b', q):
        return today - _td(days=1)

    m_ago = re.search(
        r'\b(a|an|\d+(?:\.\d+)?)\s+(day|week|month|year)s?\s+ago\b', q,
    )
    if m_ago:
        amount = 1.0 if m_ago.group(1) in ("a", "an") else float(m_ago.group(1))
        unit   = m_ago.group(2)
        days   = {"day": 1, "week": 7, "month": 30.44, "year": 365.25}[unit]
        return today - _td(days=int(round(amount * days)))

    match = re.search(
        r'\b(?:last|this)\s+(monday|mon|tuesday|tue|tues|wednesday|wed'
        r'|thursday|thu|thur|thurs|friday|fri|saturday|sat|sunday|sun)\b',
        q,
    )
    if not match:
        return None

    target_weekday = _WEEKDAYS[match.group(1)]
    days_back = (today.weekday() - target_weekday) % 7
    if days_back == 0:
        days_back = 7
    return today - _td(days=days_back)


def resolve_absolute_date(question: str) -> date | None:
    """Parse an explicit calendar date from a question.

    Handles: "May 12 2020", "May 12, 2020", "12 May 2020",
             "2020-05-12", "2020/05/12".
    Returns None if no parseable date is found.
    """
    _MONTHS = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    month_pat = (
        r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?'
        r'|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?'
        r'|dec(?:ember)?)'
    )
    q = question.lower()

    m = re.search(rf'\b({month_pat})\s+(\d{{1,2}})[,\s]+(\d{{4}})\b', q)
    if m:
        try:
            mon = _MONTHS[m.group(1)[:3]]
            return date(int(m.group(3)), mon, int(m.group(2)))
        except ValueError:
            pass

    m = re.search(rf'\b(\d{{1,2}})\s+({month_pat})\s+(\d{{4}})\b', q)
    if m:
        try:
            mon = _MONTHS[m.group(2)[:3]]
            return date(int(m.group(3)), mon, int(m.group(1)))
        except ValueError:
            pass

    m = re.search(r'\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b', q)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    return None


def detect_duration(question: str) -> tuple[date, date] | None:
    """Parse 'last/past N <unit>' phrases into a concrete (start, today) range.

    Supports any positive integer or decimal amount:
      'last 54 days', 'past 60 days', 'last 2.5 years', 'last 18 months'.

    Returns None when the question has no such pattern.
    Does NOT match bare 'last year' / 'last month' (handled by detect_range).
    """
    from datetime import timedelta

    today = datetime.now(timezone.utc).date()
    q = question.lower()

    m = re.search(
        r'\b(?:last|past)\s+(\d+(?:\.\d+)?)\s*(day|week|month|year)s?\b', q,
    )
    if not m:
        return None

    amount = float(m.group(1))
    unit   = m.group(2)
    delta_map = {"day": 1, "week": 7, "month": 30.44, "year": 365.25}
    if unit not in delta_map:
        return None

    start_date = today - timedelta(days=int(round(amount * delta_map[unit])))
    return start_date, today


def resolve_date_range(question: str) -> tuple[date, date] | None:
    """Parse an explicit date range from a question.

    Handles patterns like:
    - "May 2023 to May 2025"
    - "from 2023-05-01 to 2025-05-31"
    - "Jan 2024 - Dec 2024"
    - "between May 2023 and May 2025"

    Returns (start_date, end_date) or None.
    """
    import calendar as _cal

    _MONTHS = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    _month_pat = (
        r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?'
        r'|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?'
        r'|dec(?:ember)?)'
    )
    _sep = r'\s*(?:to|-{1,2}|through|and)\s*'
    q = question.lower()

    def _mstart(mon_str: str, yr: int) -> date:
        return date(yr, _MONTHS[mon_str[:3]], 1)

    def _mend(mon_str: str, yr: int) -> date:
        mon = _MONTHS[mon_str[:3]]
        return date(yr, mon, _cal.monthrange(yr, mon)[1])

    # "Month YYYY to Month YYYY"
    m = re.search(
        rf'({_month_pat})\s+(\d{{4}})\s*{_sep}({_month_pat})\s+(\d{{4}})', q,
    )
    if m:
        try:
            start = _mstart(m.group(1), int(m.group(2)))
            end   = _mend(m.group(3), int(m.group(4)))
            if start < end:
                return start, end
        except ValueError:
            pass

    # "YYYY-MM-DD to YYYY-MM-DD"
    m = re.search(
        r'\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})'
        r'\s*(?:to|-)\s*'
        r'(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b',
        q,
    )
    if m:
        try:
            start = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            end   = date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
            if start < end:
                return start, end
        except ValueError:
            pass

    # "Month DD YYYY to Month DD YYYY"
    m = re.search(
        rf'({_month_pat})\s+(\d{{1,2}})[,\s]+(\d{{4}})'
        rf'\s*{_sep}'
        rf'({_month_pat})\s+(\d{{1,2}})[,\s]+(\d{{4}})',
        q,
    )
    if m:
        try:
            start = date(int(m.group(3)), _MONTHS[m.group(1)[:3]], int(m.group(2)))
            end   = date(int(m.group(6)), _MONTHS[m.group(4)[:3]], int(m.group(5)))
            if start < end:
                return start, end
        except ValueError:
            pass

    return None


def range_for_date(target: date) -> str:
    """Return the smallest supported range shortcode that covers the target date."""
    today = datetime.now(timezone.utc).date()
    delta = (today - target).days
    if delta <= 7:       return "1W"
    if delta <= 31:      return "1M"
    if delta <= 92:      return "3M"
    if delta <= 183:     return "6M"
    if delta <= 365:     return "1Y"
    if delta <= 365 * 3: return "3Y"
    return "5Y"


def extract_date_context(question: str) -> str | None:
    """Return a human-readable date context string from embedded year/month references."""
    dates = re.findall(
        r'\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2}|'
        r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+20\d{2}|'
        r'20\d{2})\b',
        question.lower(),
    )
    if len(dates) >= 2:
        return f"User is asking about the period from {dates[0]} to {dates[1]}."
    if len(dates) == 1:
        return f"User is asking about {dates[0]}."
    return None


# ── MCP tool wrapper ──────────────────────────────────────────────────────

@mcp.tool()
async def parse_question(question: str) -> dict:
    """Parse a natural language question and return structured intent.

    Extracts all information needed to route the question to the right data
    tools: which stocks are mentioned, what time range applies, whether it's
    about news vs. price, and any specific dates.

    Use this before fetching market data to understand what the user wants.

    Returns:
        symbols:        list of detected ticker symbols (may be empty)
        sector_label:   detected sector name or None
        is_all_stocks:  True if the question asks about the whole universe
        range:          detected time-range shortcode (e.g. "1M", "3Y") or None
        resolved_date:  specific date mentioned (ISO string) or None
        date_range:     [start, end] date range as ISO strings, or None
        is_news:        True if the question is about news/headlines
        date_context:   human-readable date context string or None
        today:          today's UTC date (ISO string)
    """
    today = datetime.now(timezone.utc).date()

    # Symbol detection
    detected_symbols = detect_symbols(question)
    sector_label: str | None = None
    is_all_stocks = False
    if not detected_symbols:
        if is_all_stocks_question(question):
            is_all_stocks = True
            detected_symbols = list(SUPPORTED_TICKERS.keys())
        else:
            sector_tickers, matched_sectors = detect_sector(question)
            if sector_tickers:
                detected_symbols = sector_tickers
                sector_label = " & ".join(matched_sectors)

    # Date resolution: duration range → explicit range → single date
    dur_range  = detect_duration(question)
    expl_range = resolve_date_range(question) if dur_range is None else None
    date_range = dur_range or expl_range
    resolved_date: date | None = None
    if date_range is None:
        resolved_date = resolve_relative_date(question) or resolve_absolute_date(question)

    # Time-range shortcode
    if date_range is not None:
        effective_range: str | None = range_for_date(date_range[0])
    elif resolved_date is not None:
        effective_range = range_for_date(resolved_date)
    else:
        effective_range = detect_range(question)

    return {
        "symbols":       detected_symbols,
        "sector_label":  sector_label,
        "is_all_stocks": is_all_stocks,
        "range":         effective_range,
        "resolved_date": str(resolved_date) if resolved_date else None,
        "date_range":    [str(date_range[0]), str(date_range[1])] if date_range else None,
        "is_news":       is_news_question(question),
        "date_context":  extract_date_context(question),
        "today":         str(today),
    }
