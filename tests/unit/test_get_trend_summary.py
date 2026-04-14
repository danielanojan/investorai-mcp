"""
get_trend_summary MCP tool.

Generates an AI narrative summary of a stock's price trend.
Supports natural language date queries:
- Specific dates: "price on 2021-04-22", "price on 22/04/2021"
- Relative dates: "price 30 days ago", "last Monday", "yesterday"
- Custom ranges: "price between Jan 2021 and Mar 2021"
- Standard ranges: 1W, 1M, 3M, 6M, 1Y, 3Y, 5Y

Auto-detects symbol and range from natural language questions.
"""
import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastmcp import Context
from sqlalchemy import select

from investorai_mcp.data.yfinance_adapter import YFinanceAdapter
from investorai_mcp.db import AsyncSessionLocal
from investorai_mcp.db.cache_manager import CacheManager
from investorai_mcp.db.models import NewsArticle, PriceHistory
from investorai_mcp.llm.citations import extract_citations
from investorai_mcp.llm.history import compress_history
from investorai_mcp.llm.litellm_client import call_llm
from investorai_mcp.llm.prompt_builder import build_prompt, compute_stats
from investorai_mcp.llm.validator import IDK_RESPONSE, validate_response
from investorai_mcp.server import mcp
from investorai_mcp.stocks import SUPPORTED_TICKERS, is_supported

_adapter = YFinanceAdapter()


# ── Range detection ───────────────────────────────────────────────────────

def _detect_range_from_question(question: str) -> str | None:
    """Detect time range from natural language. Returns None if not detected."""
    q = question.lower()

    if any(w in q for w in ["5 year", "5year", "five year", "5yr"]):
        return "5Y"
    if any(w in q for w in ["3 year", "3year", "three year", "3yr"]):
        return "3Y"
    if any(w in q for w in ["1 year", "1year", "one year", "this year",
                             "past year", "last year", "12 month"]):
        return "1Y"
    if any(w in q for w in ["6 month", "6month", "six month",
                             "half year", "last 6"]):
        return "6M"
    if any(w in q for w in ["3 month", "3month", "three month",
                             "quarter", "last 3 month"]):
        return "3M"
    if any(w in q for w in ["1 month", "1month", "one month",
                             "30 day", "4 week", "5 week", "last month"]):
        return "1M"
    if any(w in q for w in ["1 week", "1week", "one week",
                             "7 day", "this week", "last week"]):
        return "1W"
    return None


# ── Symbol detection ──────────────────────────────────────────────────────

def _detect_symbol_from_question(question: str) -> str | None:
    """Detect ticker symbol from question text."""
    q_upper = question.upper()
    q_lower = question.lower()

    # Check exact symbol match first
    for symbol in SUPPORTED_TICKERS:
        if (f" {symbol} " in f" {q_upper} " or
                q_upper.startswith(f"{symbol} ") or
                q_upper.endswith(f" {symbol}")):
            return symbol

    # Check company name match
    for symbol, info in SUPPORTED_TICKERS.items():
        name_lower = info["name"].lower()
        first_word = name_lower.split()[0]
        if len(first_word) > 3 and first_word in q_lower:
            return symbol

    return None


# ── Date resolution ───────────────────────────────────────────────────────

def _resolve_relative_date(question: str) -> date | None:
    """
    Resolve relative date references to actual dates.
    Handles: yesterday, N days ago, N weeks ago, last Monday etc.
    """
    q     = question.lower()
    today = datetime.now(timezone.utc).date()

    if "yesterday" in q:
        return today - timedelta(days=1)

    days_match = re.search(r'(\d+)\s*days?\s*ago', q)
    if days_match:
        return today - timedelta(days=int(days_match.group(1)))

    weeks_match = re.search(r'(\d+)\s*weeks?\s*ago', q)
    if weeks_match:
        return today - timedelta(weeks=int(weeks_match.group(1)))

    weekdays = {
        "monday": 0, "tuesday": 1, "wednesday": 2,
        "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6
    }
    for day_name, day_num in weekdays.items():
        if f"last {day_name}" in q or f"past {day_name}" in q:
            days_back = (today.weekday() - day_num) % 7
            if days_back == 0:
                days_back = 7
            return today - timedelta(days=days_back)

    return None


def _resolve_explicit_date(question: str) -> date | None:
    """
    Resolve explicit date references.
    Handles: 2021-04-22, 22/04/2021, April 22 2021, Apr 22 2021
    """
    # ISO format: 2021-04-22
    iso_match = re.search(r'\b(20\d{2})-(\d{2})-(\d{2})\b', question)
    if iso_match:
        try:
            return date(
                int(iso_match.group(1)),
                int(iso_match.group(2)),
                int(iso_match.group(3))
            )
        except ValueError:
            pass

    # DD/MM/YYYY
    slash_match = re.search(r'\b(\d{1,2})/(\d{1,2})/(20\d{2})\b', question)
    if slash_match:
        try:
            return date(
                int(slash_match.group(3)),
                int(slash_match.group(2)),
                int(slash_match.group(1))
            )
        except ValueError:
            try:
                return date(
                    int(slash_match.group(3)),
                    int(slash_match.group(1)),
                    int(slash_match.group(2))
                )
            except ValueError:
                pass

    # "April 22 2021" or "Apr 22, 2021"
    month_names = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
        'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
        'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }
    for month_abbr, month_num in month_names.items():
        pattern = rf'{month_abbr}\w*\s+(\d{{1,2}}),?\s+(20\d{{2}})'
        match   = re.search(pattern, question.lower())
        if match:
            try:
                return date(
                    int(match.group(2)),
                    month_num,
                    int(match.group(1))
                )
            except ValueError:
                pass

    return None


def _extract_date_context(question: str) -> str | None:
    """Extract date range context for prompt enrichment."""
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


# ── DB helpers ────────────────────────────────────────────────────────────

async def _get_price_for_date(
    session, symbol: str, target_date: date
) -> tuple[date, float] | None:
    """Get price for a specific date or nearest trading day (±5 days)."""
    stmt = select(PriceHistory).where(
        PriceHistory.symbol == symbol,
        PriceHistory.date   == target_date,
    )
    result = await session.execute(stmt)
    row    = result.scalar_one_or_none()
    if row:
        return row.date, round(row.adj_close, 2)

    for delta in range(1, 6):
        for d in [target_date - timedelta(days=delta),
                  target_date + timedelta(days=delta)]:
            stmt = select(PriceHistory).where(
                PriceHistory.symbol == symbol,
                PriceHistory.date   == d,
            )
            result = await session.execute(stmt)
            row    = result.scalar_one_or_none()
            if row:
                return row.date, round(row.adj_close, 2)

    return None


async def _get_prices_for_custom_range(
    session, symbol: str, start: date, end: date
) -> list[tuple[date, float]]:
    """Get daily prices between two dates."""
    stmt = (
        select(PriceHistory)
        .where(
            PriceHistory.symbol == symbol,
            PriceHistory.date   >= start,
            PriceHistory.date   <= end,
        )
        .order_by(PriceHistory.date.asc())
    )
    result = await session.execute(stmt)
    rows   = result.scalars().all()
    return [(r.date, round(r.adj_close, 2)) for r in rows]


# ── Main tool ─────────────────────────────────────────────────────────────

@mcp.tool()
async def get_trend_summary(
    ticker_symbol: str,
    range: Literal["1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"] = "1Y",
    question: str = "Summarise this stock's recent performance.",
    history: list[dict] | None = None,
    ctx: Context | None = None,
) -> dict:
    """Generate an AI narrative summary of a stock's price trend.

    Supports natural language queries about any date or date range
    within the last 5 years. Auto-detects the stock symbol and time
    range from the question text.

    Examples:
    - "What was Tesla's price on 2021-04-22?"
    - "What was AAPL price 30 days ago?"
    - "What was Microsoft price last Monday?"
    - "How did NVDA perform between Jan 2025 and Mar 2025?"
    - "How has Apple performed this year?"

    Args:
        ticker_symbol: Default ticker if none detected in question.
        range:         Default range if none detected in question.
        question:      Natural language question from the user.
        history:       Optional compressed chat history.

    Returns:
        Dict with AI summary, citations, validation status, stats.
    """
    # Detect effective symbol and range
    detected_symbol  = _detect_symbol_from_question(question)
    effective_symbol = (
        detected_symbol if detected_symbol
        else ticker_symbol.strip().upper()
    )

    if not is_supported(effective_symbol):
        return {
            "error":   True,
            "code":    "TICKER_NOT_SUPPORTED",
            "message": f"{effective_symbol} is not in the InvestorAI supported universe.",
            "hint":    "Use search_ticker to find supported stocks.",
        }

    detected_range  = _detect_range_from_question(question)
    effective_range = detected_range if detected_range else range

    # Expand to 5Y if question mentions a past year
    past_years = re.findall(r'\b(202[0-4])\b', question)
    if past_years:
        effective_range = "5Y"

    session_hash = hashlib.sha256(
        f"{effective_symbol}{datetime.now(timezone.utc).date()}".encode()
    ).hexdigest()[:16]

    # Resolve specific or relative dates
    specific_date = _resolve_explicit_date(question)
    relative_date = _resolve_relative_date(question)
    target_date   = specific_date or relative_date

    # Detect custom date range (two explicit dates in question)
    date_matches = re.findall(
        r'\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2}|'
        r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+20\d{2})\b',
        question.lower()
    )
    has_custom_range = len(date_matches) >= 2

    price_data_block = ""

    async with AsyncSessionLocal() as session:
        manager = CacheManager(session, _adapter)
        await manager.ensure_ticker_exists(effective_symbol)
        cache_result = await manager.get_prices(effective_symbol, effective_range)

        # Specific date lookup
        if target_date and not has_custom_range:
            price_result = await _get_price_for_date(
                session, effective_symbol, target_date
            )
            if price_result:
                actual_date, price = price_result
                price_data_block = (
                    f"\nSPECIFIC DATE PRICE DATA:\n"
                    f"- {effective_symbol} on {actual_date}: ${price:.2f}\n"
                    f"  (nearest trading day to {target_date})\n"
                )
            else:
                price_data_block = (
                    f"\nSPECIFIC DATE PRICE DATA:\n"
                    f"- No data found for {effective_symbol} around {target_date}\n"
                    f"  (data may not go back that far — oldest data is 5 years)\n"
                )

        # Custom date range
        elif has_custom_range:
            try:
                from dateutil import parser as dateparser
                start_date   = dateparser.parse(date_matches[0]).date()
                end_date     = dateparser.parse(date_matches[1]).date()
                range_prices = await _get_prices_for_custom_range(
                    session, effective_symbol, start_date, end_date
                )
                if range_prices:
                    step    = max(1, len(range_prices) // 20)
                    sampled = range_prices[::step]
                    rows_text = "\n".join(
                        f"  {d}: ${p:.2f}" for d, p in sampled
                    )
                    start_p = range_prices[0][1]
                    end_p   = range_prices[-1][1]
                    ret_pct = round((end_p - start_p) / start_p * 100, 2)
                    price_data_block = (
                        f"\nCUSTOM RANGE DATA ({start_date} to {end_date}):\n"
                        f"- Start: ${start_p:.2f}\n"
                        f"- End:   ${end_p:.2f}\n"
                        f"- Return: {ret_pct:+.2f}%\n"
                        f"- Sample prices:\n{rows_text}\n"
                    )
                else:
                    price_data_block = (
                        f"\nCUSTOM RANGE DATA:\n"
                        f"- No data found between {start_date} and {end_date}\n"
                    )
            except Exception:
                pass

        # Fetch news
        news_stmt   = (
            select(NewsArticle)
            .where(NewsArticle.symbol == effective_symbol)
            .order_by(NewsArticle.published_at.desc())
            .limit(5)
        )
        news_result = await session.execute(news_stmt)
        recent_news = list(news_result.scalars().all())

    if not cache_result.data:
        return {
            "error":   True,
            "code":    "DATA_UNAVAILABLE",
            "message": f"No price data available for {effective_symbol}.",
        }

    stats = compute_stats(effective_symbol, effective_range, cache_result.data)
    if stats is None:
        return {
            "error":   True,
            "code":    "DATA_UNAVAILABLE",
            "message": f"Could not compute statistics for {effective_symbol}.",
        }

    # Compress history
    compressed_history = None
    if history:
        compressed_history = await compress_history(
            history, session_hash=session_hash
        )

    # Enrich question with date context
    date_context   = _extract_date_context(question)
    final_question = question
    if date_context:
        final_question = f"{question}\nContext: {date_context}"

    # Build prompt
    messages = build_prompt(
        stats=stats,
        question=final_question,
        news=recent_news if recent_news else None,
        history=compressed_history,
    )

    # Inject specific price data block into user message
    if price_data_block:
        last_msg    = messages[-1]
        messages[-1] = {
            **last_msg,
            "content": last_msg["content"] + price_data_block,
        }

    # Call LLM
    try:
        raw_response = await call_llm(
            messages=messages,
            session_hash=session_hash,
            tool_name="get_trend_summary",
        )
    except RuntimeError as e:
        return {
            "error":   True,
            "code":    "LLM_UNAVAILABLE",
            "message": str(e),
        }

    # Validate and extract citations
    validation      = validate_response(raw_response, stats)
    citation_result = extract_citations(validation.response)

    return {
        "symbol":            effective_symbol,
        "range":             effective_range,
        "question_symbol":   detected_symbol,
        "summary":           citation_result.clean_text,
        "citations": [
            {"type": c.citation_type, "date": c.date}
            for c in citation_result.db_citations
        ] + [
            {"type": c.citation_type, "publisher": c.publisher, "url": c.url}
            for c in citation_result.news_citations
        ],
        "validation_passed": validation.passed,
        "is_stale":          cache_result.is_stale,
        "data_age_hours":    round(cache_result.data_age_hours, 2),
        "stats": {
            "start_price":       stats.start_price,
            "end_price":         stats.end_price,
            "period_return_pct": stats.period_return_pct,
            "high_price":        stats.high_price,
            "low_price":         stats.low_price,
            "volatility_pct":    stats.volatility_pct,
            "trading_days":      stats.trading_days,
        },
    }