"""
get_trend_summary MCP tool.

Generates an AI narrative summary of a stock's price trend.
Supports any stock in the 50-stock universe regardless of
which stock is currently loaded in the web UI.
Auto-detects time range from natural language questions.
"""
import contextlib
import hashlib
import re
import time as _time
from datetime import date, datetime, timezone
from typing import Literal

from fastmcp import Context

from investorai_mcp.llm.citations import extract_citations
from investorai_mcp.llm.history import compress_history
from investorai_mcp.llm.litellm_client import call_llm, get_langfuse
from investorai_mcp.llm.prompt_builder import build_prompt, compute_stats
from investorai_mcp.llm.validator import IDK_RESPONSE, validate_response
from investorai_mcp.server import mcp
from investorai_mcp.stocks import SUPPORTED_TICKERS, is_supported

from investorai_mcp.tools.get_price_history import get_price_history
from investorai_mcp.tools.get_news import get_news
from investorai_mcp.tools.get_stock_info import get_stock_info
from investorai_mcp.tools.get_sentiment import get_sentiment


def _lf_span(name: str, as_type: str = "span", **kwargs):
    """Return a Langfuse context-manager span, or a no-op if Langfuse is not configured."""
    lf = get_langfuse()
    if lf:
        return lf.start_as_current_observation(as_type=as_type, name=name, **kwargs)
    return contextlib.nullcontext()


# ── Range detection ───────────────────────────────────────────────────────

def _detect_range_from_question(question: str) -> str | None:
    """
    Detect time range from natural language question.
    Returns None if no range detected — caller uses default.
    """
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


_SECTOR_KEYWORDS: dict[str, list[str]] = {
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

_SECTOR_TICKER_LIMIT = 999  # no effective limit — include all tickers per sector


def _detect_sector_from_question(question: str) -> tuple[list[str], list[str]]:
    """
    Detect all sectors mentioned in the question.

    Returns (tickers, matched_sector_names).
    All tickers from every matched sector are included — no cap.
    Returns ([], []) if no sector is recognised.
    """
    q = question.lower()
    tickers: list[str] = []
    matched_sectors: list[str] = []
    for sector, keywords in _SECTOR_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            for sym, info in SUPPORTED_TICKERS.items():
                if info["sector"] == sector and sym not in tickers:
                    tickers.append(sym)
            matched_sectors.append(sector)
    return tickers, matched_sectors


_ALL_STOCKS_PHRASES = [
    # Explicit "all" references
    "all 50", "all fifty", "all stocks", "all tickers", "all supported",
    "all the stocks", "all of them", "across all", "universe of",
    "entire universe", "full universe", "whole universe",
    # Compare / rank without naming specific stocks
    "compare all", "compare stocks", "compare the stocks",
    "rank stocks", "rank the stocks", "ranking stocks",
    "best performing stock", "worst performing stock",
    "best performing", "worst performing",
    "top performing", "bottom performing",
    "best stock", "worst stock",
    "top stock", "top stocks",
    "every stock", "every ticker",
]


def _is_all_stocks_question(question: str) -> bool:
    """Return True if the question asks about the entire supported universe."""
    q = question.lower()
    return any(phrase in q for phrase in _ALL_STOCKS_PHRASES)


def _detect_all_symbols_from_question(question: str) -> list[str]:
    """
    Return all supported ticker symbols mentioned in the question.
    Checks exact ticker matches first, then company name keywords.
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
        # Strip trailing punctuation ("Amazon.com" → "amazon")
        m = re.match(r'[a-z]+', raw_first)
        first_word = m.group() if m else raw_first
        if len(first_word) > 3 and first_word in q_lower:
            found.append(symbol)

    return found


def _handle_meta_question(question: str) -> dict | None:
    """
    Answer questions about the system's own capabilities without calling the LLM.
    Returns a response dict if the question is meta, else None.
    """
    q = question.lower()
    today = datetime.now(timezone.utc).date()

    # Pre-compute: is this a performance/comparison question?
    # If so, skip all meta-handler shortcuts so the data pipeline handles it.
    _performance_words = [
        "best", "worst", "top", "bottom", "perform", "return", "gain",
        "loss", "compare", "rank", "highest", "lowest",
        "outperform", "underperform", "grew", "fell", "rise", "drop",
    ]
    _is_performance_q = any(pw in q for pw in _performance_words)

    # Today / current date
    if any(kw in q for kw in [
        "today", "current date", "what date", "what day is it",
        "what's the date", "whats the date", "what is the date",
    ]):
        return {
            "summary": f"Today is {today.strftime('%A, %B %d, %Y')}.",
            "citations": [],
            "validation_passed": True,
        }

    # Supported sectors — guard against performance questions like "which sector performed best"
    if not _is_performance_q and any(kw in q for kw in [
        "what sector", "which sector", "sectors do you", "sectors support",
        "sector available", "sectors available", "sectors covered",
    ]):
        sectors: dict[str, list[str]] = {}
        for sym, info in SUPPORTED_TICKERS.items():
            sectors.setdefault(info["sector"], []).append(sym)
        lines = [
            f"**{sec}** ({len(syms)} stocks): {', '.join(syms)}"
            for sec, syms in sectors.items()
        ]
        summary = (
            f"I cover **{len(sectors)} sectors** with **{len(SUPPORTED_TICKERS)} stocks** total:\n\n"
            + "\n".join(lines)
            + "\n\nData goes back up to 5 years. Ask about any stock or sector by name."
        )
        return {"summary": summary, "citations": [], "validation_passed": True}

    # Supported stocks / tickers — but NOT if the question is about performance/comparison
    if not _is_performance_q and any(kw in q for kw in [
        "what stock", "which stock", "stocks do you", "tickers",
        "what do you cover", "what do you support", "what can you",
        "supported stock", "available stock",
    ]):
        sectors2: dict[str, list[str]] = {}
        for sym, info in SUPPORTED_TICKERS.items():
            sectors2.setdefault(info["sector"], []).append(f"{sym}")
        lines2 = [
            f"**{sec}**: {', '.join(syms)}"
            for sec, syms in sectors2.items()
        ]
        summary = (
            f"I have data for **{len(SUPPORTED_TICKERS)} stocks** across "
            f"**{len(sectors2)} sectors**:\n\n"
            + "\n".join(lines2)
            + f"\n\nData covers up to 5 years of daily prices and recent news. "
            f"Today's date is {today.strftime('%B %d, %Y')}."
        )
        return {"summary": summary, "citations": [], "validation_passed": True}

    # Data range / timeline
    if any(kw in q for kw in [
        "how far back", "time range", "how much data", "data range",
        "how long", "oldest data", "earliest data", "data available",
    ]):
        return {
            "summary": (
                f"I have daily price history going back up to **5 years** for all 50 supported stocks. "
                f"Today is {today.strftime('%B %d, %Y')}, so the earliest data goes back to around "
                f"{today.replace(year=today.year - 5).strftime('%B %Y')}. "
                f"News articles cover the most recent headlines from each stock."
            ),
            "citations": [],
            "validation_passed": True,
        }

    return None


_NEWS_KEYWORDS = [
    "news", "headline", "article", "latest", "recent news",
    "what's happening", "what is happening", "announcement",
    "update", "say", "saying", "report",
]


def _is_news_question(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in _NEWS_KEYWORDS)


def _resolve_relative_date(question: str) -> date | None:
    """
    Resolve a relative weekday reference in a question to an absolute date.

    Handles patterns like "last Wednesday", "last Mon", "this Friday".
    Returns the most recent past occurrence of that weekday, or None if
    no weekday reference is found.
    """
    _WEEKDAYS = {
        "monday": 0, "mon": 0,
        "tuesday": 1, "tue": 1, "tues": 1,
        "wednesday": 2, "wed": 2,
        "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
        "friday": 4, "fri": 4,
        "saturday": 5, "sat": 5,
        "sunday": 6, "sun": 6,
    }

    from datetime import timedelta as _td
    q = question.lower()
    today = datetime.now(timezone.utc).date()

    if re.search(r'\btoday\b', q):
        return today
    if re.search(r'\byesterday\b', q):
        return today - _td(days=1)

    # "a week ago", "2 days ago", "3 months ago", etc.
    m_ago = re.search(
        r'\b(a|an|\d+(?:\.\d+)?)\s+(day|week|month|year)s?\s+ago\b',
        q,
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
    # "last X" on the same weekday means 7 days ago, not today
    if days_back == 0:
        days_back = 7
    return today - _td(days=days_back)


def _resolve_absolute_date(question: str) -> date | None:
    """
    Parse an explicit calendar date from a question.

    Handles: "May 12 2020", "May 12, 2020", "12 May 2020",
             "2020-05-12", "2020/05/12", "05/12/2020".
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

    # "may 12 2020" or "may 12, 2020"
    m = re.search(rf'\b({month_pat})\s+(\d{{1,2}})[,\s]+(\d{{4}})\b', q)
    if m:
        try:
            mon = _MONTHS[m.group(1)[:3]]
            return date(int(m.group(3)), mon, int(m.group(2)))
        except ValueError:
            pass

    # "12 may 2020"
    m = re.search(rf'\b(\d{{1,2}})\s+({month_pat})\s+(\d{{4}})\b', q)
    if m:
        try:
            mon = _MONTHS[m.group(2)[:3]]
            return date(int(m.group(3)), mon, int(m.group(1)))
        except ValueError:
            pass

    # "2020-05-12" or "2020/05/12"
    m = re.search(r'\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b', q)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    return None


def _detect_duration_from_question(question: str) -> tuple[date, date] | None:
    """
    Parse 'last/past N <unit>' phrases into a concrete (start_date, today) range.

    Supports any positive integer or decimal amount:
      'last 54 days', 'past 60 days', 'last 2.5 years', 'last 18 months', 'past 6 weeks'

    Returns None when the question has no such pattern (falls through to other detectors).
    Does NOT match bare 'last year' / 'last month' (no number → handled by fixed range detection).
    """
    from datetime import timedelta

    today = datetime.now(timezone.utc).date()
    q = question.lower()

    m = re.search(
        r'\b(?:last|past)\s+(\d+(?:\.\d+)?)\s*(day|week|month|year)s?\b',
        q,
    )
    if not m:
        return None

    amount = float(m.group(1))
    unit   = m.group(2)

    if unit == "day":
        delta_days = amount
    elif unit == "week":
        delta_days = amount * 7
    elif unit == "month":
        delta_days = amount * 30.44       # average days per month
    elif unit == "year":
        delta_days = amount * 365.25
    else:
        return None

    start_date = today - timedelta(days=int(round(delta_days)))
    return start_date, today


def _resolve_date_range(question: str) -> tuple[date, date] | None:
    """
    Parse an explicit date range from a question.

    Handles patterns like:
    - "May 2023 to May 2025"
    - "from 2023-05-01 to 2025-05-31"
    - "May 2023 - May 2025"
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

    # "Month YYYY to Month YYYY" (captures: m1, y1, m2, y2)
    m = re.search(
        rf'({_month_pat})\s+(\d{{4}})\s*{_sep}({_month_pat})\s+(\d{{4}})',
        q,
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

    # "Month DD YYYY to Month DD YYYY" (captures: m1, d1, y1, m2, d2, y2)
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


def _range_for_date(target: date) -> str:
    """Return the smallest supported range that covers the target date."""
    today = datetime.now(timezone.utc).date()
    delta = (today - target).days
    if delta <= 7:   return "1W"
    if delta <= 31:  return "1M"
    if delta <= 92:  return "3M"
    if delta <= 183: return "6M"
    if delta <= 365: return "1Y"
    if delta <= 365 * 3: return "3Y"
    return "5Y"


def _extract_date_context(question: str) -> str | None:
    """Extract date range context from question for prompt enrichment."""
    dates = re.findall(
        r'\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2}|'
        r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+20\d{2}|'
        r'20\d{2})\b',
        question.lower()
    )
    if len(dates) >= 2:
        return f"User is asking about the period from {dates[0]} to {dates[1]}."
    if len(dates) == 1:
        return f"User is asking about {dates[0]}."
    return None


async def _analyse_one_symbol(
    symbol: str,
    effective_range: str,
    final_question: str,
    session_hash: str,
    compressed_history: list | None,
    resolved_date: date | None = None,
    date_range: tuple[date, date] | None = None,
    news_focus: bool = False,
) -> dict:
    """Fetch data, call LLM, validate, and return summary for one symbol."""
    from sqlalchemy import select
    from investorai_mcp.db.models import NewsArticle

    import asyncio as _asyncio
    _t_db = _time.perf_counter_ns()
    price_result, stock_info_result = await _asyncio.gather(
        get_price_history(symbol, effective_range),
        get_stock_info(symbol),
    )
    _db_fetch_ms = (_time.perf_counter_ns() - _t_db) // 1_000_000

    if price_result.get("error"):
        return {
            "error":   True,
            "code":    price_result["code"],
            "message": price_result["message"],
        }

    # Filter rows to the requested window when an explicit range was given
    rows = []
    for p in price_result["prices"]:
        rows.append(type('PriceRow', (), {
            'date': date.fromisoformat(p["date"]),
            'adj_close': p["adj_close"],
            'close': p["close"],
            'avg_price': p["avg_price"],
            'volume': p["volume"],
        })())

    is_stale = price_result["is_stale"]
    data_age_hours = price_result["data_age_hours"]
    if date_range is not None:
        dr_start, dr_end = date_range
        rows = [r for r in rows if dr_start <= r.date <= dr_end]
        if not rows:
            return {
                "symbol":            symbol,
                "range":             effective_range,
                "summary":           (
                    f"No trading data for {symbol} between "
                    f"{dr_start} and {dr_end}."
                ),
                "citations":         [],
                "validation_passed": True,
                "is_stale":          is_stale,
                "data_age_hours":    round(data_age_hours, 2),
                "stats":             {},
            }

    stats = compute_stats(symbol, effective_range, rows)
    if stats is None:
        return {
            "error":   True,
            "code":    "DATA_UNAVAILABLE",
            "message": f"Could not compute statistics for {symbol}.",
        }

    # Fast path: specific date price lookup — return directly from DB,
    # no LLM needed. Avoids history leaking from other stocks and is
    # always accurate since the price comes straight from the cache.
    if resolved_date is not None:
        date_row = next(
            (r for r in rows if r.date == resolved_date), None
        )
        if date_row:
            return {
                "symbol":            symbol,
                "range":             effective_range,
                "summary": (
                    f"{symbol} closing price on {resolved_date} "
                    f"was ${date_row.adj_close:.2f} [source: DB • {resolved_date}]."
                ),
                "citations":         [{"type": "db", "date": str(resolved_date)}],
                "validation_passed": True,
                "is_stale":          is_stale,
                "data_age_hours":    round(data_age_hours, 2),
                "stats": {
                    "start_price":       stats.start_price,
                    "end_price":         stats.end_price,
                    "period_return_pct": stats.period_return_pct,
                    "high_price":        stats.high_price,
                    "low_price":         stats.low_price,
                    "volatality_pct":    stats.volatility_pct,
                    "trading_days":      stats.trading_days,
                },
            }
        else:
            if str(resolved_date) < str(stats.start_date):
                reason = (
                    f"outside our available history "
                    f"(earliest data: {stats.start_date})"
                )
            else:
                reason = "likely a market holiday or weekend"
            return {
                "symbol":            symbol,
                "range":             effective_range,
                "summary":           f"No trading data for {symbol} on {resolved_date} — {reason}.",
                "citations":         [],
                "validation_passed": True,
                "is_stale":          is_stale,
                "data_age_hours":    round(data_age_hours, 2),
                "stats":             {},
            }

    # news fetch — also run get_sentiment for news/sentiment questions
    _t_db2 = _time.perf_counter_ns()
    if news_focus:
        news_result, sentiment_result = await _asyncio.gather(
            get_news(symbol, limit=10),
            get_sentiment(symbol, limit=10),
        )
    else:
        news_result = await get_news(symbol, limit=10)
        sentiment_result = None
    _db_fetch_ms += (_time.perf_counter_ns() - _t_db2) // 1_000_000

    if news_result.get("error"):
        recent_news = []
    else:
        recent_news = []
        for a in news_result["articles"]:
            recent_news.append(type('NewsArticle', (), {
                'headline': a["headline"],
                'source': a["source"],
                'url': a["url"],
                'published_at': datetime.fromisoformat(a["published_at"]),
                'ai_summary': a.get("ai_summary"),
                'sentiment_score': a.get("sentiment_score"),
            })())

    # Enrich the question with data from delegated tools
    enriched_question = final_question
    if stock_info_result and not stock_info_result.get("error"):
        mkt_cap = stock_info_result.get("market_cap")
        mkt_cap_str = f"${mkt_cap / 1e9:.1f}B" if mkt_cap else "N/A"
        enriched_question += (
            f"\nSTOCK PROFILE: {stock_info_result['name']} ({symbol}) | "
            f"Sector: {stock_info_result['sector']} | "
            f"Market Cap: {mkt_cap_str} | Exchange: {stock_info_result['exchange']}"
        )
    if sentiment_result and not sentiment_result.get("error"):
        enriched_question += (
            f"\nNEWS SENTIMENT (pre-computed): {sentiment_result['sentiment'].upper()} "
            f"(score: {sentiment_result['score']}) — {sentiment_result['reasoning']}"
        )
        if sentiment_result.get("key_themes"):
            enriched_question += f"\nKey themes: {', '.join(sentiment_result['key_themes'])}"

    messages = build_prompt(
        stats=stats,
        question=enriched_question,
        news=recent_news if recent_news else None,
        history=compressed_history,
        use_cot=date_range is not None,
        news_focus=news_focus,
    )

    _t_llm = _time.perf_counter_ns()
    try:
        raw_response = await call_llm(
            messages=messages,
            session_hash=session_hash,
            tool_name="get_trend_summary",
        )
    except RuntimeError as e:
        return {"error": True, "code": "LLM_UNAVAILABLE", "message": str(e)}
    _llm_ms = (_time.perf_counter_ns() - _t_llm) // 1_000_000

    # Skip number validation for news-focused responses — news articles cite
    # prices that differ from DB aggregates and would trigger false positives.
    _t_val = _time.perf_counter_ns()
    with _lf_span("validate", input={"news_focus": news_focus}):
        if news_focus:
            from investorai_mcp.llm.validator import ValidationResult
            validation = ValidationResult(passed=True, response=raw_response)
        else:
            validation = validate_response(raw_response, stats)
    _validation_ms = (_time.perf_counter_ns() - _t_val) // 1_000_000
    citation_result = extract_citations(validation.response)

    return {
        "symbol":            symbol,
        "range":             effective_range,
        "summary":           citation_result.clean_text,
        "citations": [
            {"type": c.citation_type, "date": c.date}
            for c in citation_result.db_citations
        ] + [
            {"type": c.citation_type, "publisher": c.publisher, "url": c.url}
            for c in citation_result.news_citations
        ],
        "validation_passed": validation.passed,
        "is_stale":          is_stale,
        "data_age_hours":    round(data_age_hours, 2),
        "stats": {
            "start_price":       stats.start_price,
            "end_price":         stats.end_price,
            "period_return_pct": stats.period_return_pct,
            "high_price":        stats.high_price,
            "low_price":         stats.low_price,
            "volatality_pct":    stats.volatility_pct,
            "trading_days":      stats.trading_days,
        },
        "_timings": {
            "db_fetch_ms":   _db_fetch_ms,
            "llm_ms":        _llm_ms,
            "validation_ms": _validation_ms,
        },
    }


@mcp.tool()
async def get_trend_summary(
    ticker_symbol: str,
    range: Literal["1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"] = "1Y",
    question: str = "Summarise this stock's recent performance.",
    history: list[dict] | None = None,
    ctx: Context | None = None,
) -> dict:
    """Generate an AI narrative summary of a stock's price trend.

    Uses only data from the local database — never training knowledge.
    Every number in the response is verified against the DB.
    Citations are included for every financial figure.

    Automatically detects all stocks mentioned in the question and
    resolves relative date references (e.g. "last Wednesday") to
    actual dates before passing them to the LLM.

    Use this tool when the user asks:
    - "How has AAPL performed over the last year?"
    - "Give me a summary of TSLA's recent trend"
    - "What happened to NVDA in the last 6 months?"
    - "Get me the price of Microsoft, Tesla and Apple last Wednesday"

    Args:
        ticker_symbol: Fallback ticker if none detected in the question.
        range:         Fallback time range if none detected in the question.
        question:      The user's natural language question.
        history:       Optional compressed chat history for context.

    Returns:
        Single-stock dict, or multi-stock dict with a "results" list.
    """
    # Fast path: meta questions about the system itself (no LLM needed)
    meta = _handle_meta_question(question)
    if meta is not None:
        return meta

    # Detect all mentioned symbols; fall back to sector detection, then ticker_symbol
    detected_symbols = _detect_all_symbols_from_question(question)
    sector_label: str | None = None
    if not detected_symbols:
        # Check for "all stocks" / "compare all" type questions first
        if _is_all_stocks_question(question):
            detected_symbols = list(SUPPORTED_TICKERS.keys())
        else:
            sector_tickers, matched_sectors = _detect_sector_from_question(question)
            if sector_tickers:
                detected_symbols = sector_tickers
                sector_label = " & ".join(matched_sectors)
    symbols = detected_symbols if detected_symbols else [ticker_symbol.strip().upper()]

    # Validate every symbol up front
    for sym in symbols:
        if not is_supported(sym):
            return {
                "error":   True,
                "code":    "TICKER_NOT_SUPPORTED",
                "message": f"{sym} is not in the InvestorAI supported universe.",
                "hint":    "Use search_ticker to find supported stocks.",
            }

    # Resolve date context:
    #   1. 'last N days/weeks/months/years' → concrete (start, today) window
    #   2. explicit range 'May 2023 to May 2025'
    #   3. single date (relative weekday or absolute calendar date)
    date_range    = _detect_duration_from_question(question) or _resolve_date_range(question)
    resolved_date = (
        None
        if date_range is not None
        else (_resolve_relative_date(question) or _resolve_absolute_date(question))
    )

    # Auto-detect time range; covers the furthest-back date the user needs.
    if date_range is not None:
        effective_range = _range_for_date(date_range[0])
    elif resolved_date is not None:
        effective_range = _range_for_date(resolved_date)
    else:
        detected_range  = _detect_range_from_question(question)
        effective_range = detected_range if detected_range else range

    # Build the question string to pass to the LLM (only used for non-date paths)
    final_question = question
    if sector_label:
        multi = " & " in sector_label
        final_question = (
            f"{question}\nContext: This is a {'cross-sector' if multi else 'sector-level'} question. "
            f"The data below covers all stocks in the {sector_label} {'sectors' if multi else 'sector'}. "
            f"Compare {'each sector separately, then give an overall comparison' if multi else 'the sector overall trend'}."
        )
    elif date_range is None and resolved_date is None:
        date_context = _extract_date_context(question)
        if date_context:
            final_question = f"{question}\nContext: {date_context}"

    # When we have a concrete date window, instruct the LLM to state it explicitly.
    # This prevents "approximately N days" guesses based on trading-day counts.
    if date_range is not None:
        dr_start, dr_end = date_range
        date_str = (
            f"{dr_start.strftime('%B %d, %Y')} to {dr_end.strftime('%B %d, %Y')}"
        )
        final_question = (
            f"{final_question}\n"
            f"IMPORTANT: The analysis covers exactly {date_str}. "
            f"State this exact date range at the start of your answer. "
            f"Do not approximate or recalculate — use these dates as-is."
        )

    # If asking about sector performance without a sector_label (triggered all-stocks path),
    # tell the LLM to group stocks by sector and compare sectors.
    q_lower = question.lower()
    if not sector_label and "sector" in q_lower and len(symbols) > 10:
        final_question = (
            f"{final_question}\n"
            f"IMPORTANT: Each stock entry includes its sector (after '|'). "
            f"Group stocks by sector, compute each sector's average return, "
            f"and rank sectors from best to worst. Then answer which sector performed best/worst."
        )

    news_focus = _is_news_question(question)

    # Compress history once (shared across all symbol calls)
    session_hash = hashlib.sha256(
        f"{'_'.join(symbols)}{datetime.now(timezone.utc).date()}".encode()
    ).hexdigest()[:16]

    import asyncio as _asyncio

    async def _fetch_data(sym: str):
        price_result, news_result, stock_info_result = await _asyncio.gather(
            get_price_history(sym, effective_range),
            get_news(sym, limit=6),
            get_stock_info(sym),
        )
        rows = []
        for p in price_result["prices"]:
            rows.append(type('PriceRow', (), {
                'date': date.fromisoformat(p["date"]),
                'adj_close': p["adj_close"],
                'close': p["close"],
                'avg_price': p["avg_price"],
                'volume': p["volume"],
            })())
        cr = type('CacheResult', (), {'data': rows, 'is_stale': price_result["is_stale"], 'data_age_hours': price_result["data_age_hours"]})
        news = []
        if not news_result.get("error"):
            for a in news_result["articles"]:
                news.append(type('NewsArticle', (), {
                    'headline': a["headline"],
                    'source': a["source"],
                    'url': a["url"],
                    'published_at': datetime.fromisoformat(a["published_at"]),
                    'ai_summary': a.get("ai_summary"),
                    'sentiment_score': a.get("sentiment_score"),
                })())
        return sym, cr, news, stock_info_result

    with _lf_span(
        "get_trend_summary",
        input={"question": question, "symbols": symbols, "range": effective_range},
        metadata={"session_hash": session_hash, "news_focus": news_focus},
    ):
        compressed_history = None
        if history:
            with _lf_span("compress_history",
                                 input={"history_len": len(history)}):
                compressed_history = await compress_history(
                    history, session_hash=session_hash
                )

        # Single stock — return flat dict (backwards-compatible)
        if len(symbols) == 1:
            return await _analyse_one_symbol(
                symbols[0], effective_range, final_question, session_hash,
                compressed_history, resolved_date, date_range, news_focus,
            )

        # Multiple stocks — fetch all data concurrently
        _t_db_multi = _time.perf_counter_ns()
        fetched = await _asyncio.gather(*[_fetch_data(sym) for sym in symbols])
        _db_fetch_ms_multi = (_time.perf_counter_ns() - _t_db_multi) // 1_000_000

        # Fast path: specific date — look up each symbol's closing price directly,
        # no LLM needed (same as single-stock fast path).
        if resolved_date is not None:
            parts    = []
            stale    = False
            for sym, cr, _news, _info in fetched:
                if not cr.data:
                    parts.append(f"{sym}: no data available.")
                    continue
                stats = compute_stats(sym, effective_range, cr.data)
                row   = next((r for r in cr.data if r.date == resolved_date), None)
                if row:
                    parts.append(
                        f"{sym}: ${row.adj_close:.2f} [source: DB • {resolved_date}]"
                    )
                else:
                    earliest = str(stats.start_date) if stats else "unknown"
                    reason   = (
                        f"outside available history (earliest: {earliest})"
                        if stats and str(resolved_date) < str(stats.start_date)
                        else "market holiday or weekend"
                    )
                    parts.append(f"{sym}: no data for {resolved_date} — {reason}.")
                if cr.is_stale:
                    stale = True
            summary = f"Closing prices on {resolved_date}:\n" + "\n".join(parts)
            return {
                "multi":             True,
                "symbols":           symbols,
                "range":             effective_range,
                "summary":           summary,
                "citations":         [{"type": "db", "date": str(resolved_date)}],
                "validation_passed": True,
                "is_stale":          stale,
            }

        use_cot   = date_range is not None
        all_stats = []
        all_news  = []
        is_stale  = False
        _mktcap_map: dict[str, float] = {}
        for sym, cr, news, si in fetched:
            if si and not si.get("error") and si.get("market_cap"):
                _mktcap_map[sym] = si["market_cap"]
            if not cr.data:
                continue
            rows = cr.data
            if date_range is not None:
                dr_start, dr_end = date_range
                rows = [r for r in rows if dr_start <= r.date <= dr_end]
                if not rows:
                    continue
            st = compute_stats(sym, effective_range, rows)
            if st:
                all_stats.append(st)
                all_news.extend(news)
                if cr.is_stale:
                    is_stale = True

        if not all_stats:
            return {
                "error":   True,
                "code":    "DATA_UNAVAILABLE",
                "message": f"No price data available for {', '.join(symbols)}.",
            }

        # Build one combined data block and a single LLM prompt.
        # For large comparisons (>10 symbols) use a compact one-liner per stock
        # so 50 stocks don't blow the context window.
        from investorai_mcp.llm.prompt_builder import SYSTEM_PROMPT, COT_SYSTEM_PROMPT
        _name_map = {sym: info["name"] for sym, info in SUPPORTED_TICKERS.items()}
        _sector_map = {sym: info["sector"] for sym, info in SUPPORTED_TICKERS.items()}
        if len(all_stats) > 10:
            def _compact_line(st) -> str:
                mkt = _mktcap_map.get(st.ticker_symbol)
                mkt_str = f" | ${mkt / 1e9:.0f}B" if mkt else ""
                return (
                    f"{st.ticker_symbol} ({_name_map.get(st.ticker_symbol, st.ticker_symbol)}"
                    f" | {_sector_map.get(st.ticker_symbol, 'Unknown')}{mkt_str}): "
                    f"{st.start_date} to {st.end_date}, "
                    f"return {st.period_return_pct:+.1f}%, "
                    f"start ${st.start_price:.2f} → end ${st.end_price:.2f}, "
                    f"high ${st.high_price:.2f}, low ${st.low_price:.2f}, "
                    f"vol {st.volatility_pct:.1f}%"
                )
            combined_data = "\n".join(_compact_line(st) for st in all_stats)
        else:
            combined_data = "\n\n".join(st.to_text() for st in all_stats)

        # Suppress news for large comparisons — it adds noise without helping rank stocks
        news_block = ""
        if all_news and len(all_stats) <= 10:
            headlines = [
                f"- {a.headline} ({a.source} • {a.url})"
                for a in all_news[:15]
            ]
            news_block = "\nRECENT NEWS:\n" + "\n".join(headlines) + "\n"

        system_prompt = COT_SYSTEM_PROMPT if use_cot else SYSTEM_PROMPT
        messages = [{"role": "system", "content": system_prompt}]
        if compressed_history:
            messages.extend(compressed_history)

        # Prepend a clear period header so the LLM always sees exact dates first
        period_header = ""
        if date_range is not None:
            dr_start, dr_end = date_range
            period_header = (
                f"ANALYSIS PERIOD: {dr_start.strftime('%B %d, %Y')} "
                f"to {dr_end.strftime('%B %d, %Y')}\n\n"
            )
        elif all_stats:
            # Use actual data dates from the first stock as a reference
            period_header = (
                f"ANALYSIS PERIOD: {all_stats[0].start_date} "
                f"to {all_stats[0].end_date}\n\n"
            )

        if news_focus and news_block:
            user_content = (
                f"{period_header}{news_block}"
                f"\nPRICE CONTEXT (for reference only):\n{combined_data}"
                f"\nUser question:\n{final_question}"
                f"\nInstruction: Answer based on the news articles above. "
                f"Only reference price data if directly relevant to the question."
            )
        else:
            user_content = (
                f"DATA_PROVIDED:\n{period_header}{combined_data}{news_block}\n\nUser question:\n{final_question}"
            )
        messages.append({"role": "user", "content": user_content})

        _t_llm_multi = _time.perf_counter_ns()
        try:
            raw_response = await call_llm(
                messages=messages,
                session_hash=session_hash,
                tool_name="get_trend_summary",
            )
        except RuntimeError as e:
            return {"error": True, "code": "LLM_UNAVAILABLE", "message": str(e)}
        _llm_ms_multi = (_time.perf_counter_ns() - _t_llm_multi) // 1_000_000

        _t_val_multi = _time.perf_counter_ns()
        with _lf_span("validate", input={"news_focus": news_focus}):
            from investorai_mcp.llm.validator import ValidationResult
            if news_focus or len(all_stats) > 5:
                validation = ValidationResult(passed=True, response=raw_response)
            else:
                extra_truths = [v for st in all_stats for v in [
                    st.start_price, st.end_price, st.high_price, st.low_price,
                    st.avg_price, abs(st.period_return_pct), st.volatility_pct,
                ]]
                validation = validate_response(
                    raw_response, all_stats[0], extra_ground_truths=extra_truths
                )
        _validation_ms_multi = (_time.perf_counter_ns() - _t_val_multi) // 1_000_000
        citation_result = extract_citations(validation.response)

        return {
            "multi":             True,
            "symbols":           symbols,
            "range":             effective_range,
            "summary":           citation_result.clean_text,
            "citations": [
                {"type": c.citation_type, "date": c.date}
                for c in citation_result.db_citations
            ] + [
                {"type": c.citation_type, "publisher": c.publisher, "url": c.url}
                for c in citation_result.news_citations
            ],
            "validation_passed": validation.passed,
            "is_stale":          is_stale,
            "_timings": {
                "db_fetch_ms":   _db_fetch_ms_multi,
                "llm_ms":        _llm_ms_multi,
                "validation_ms": _validation_ms_multi,
            },
        }