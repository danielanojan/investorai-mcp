"""
get_system_info MCP tool.

Answers meta questions about the system's own capabilities — which stocks
and sectors are supported, how far back data goes, and today's date.

The core logic lives in the synchronous helper `handle_meta_question` so it
can be imported and unit-tested without async overhead.  The MCP tool wrapper
is async to match the FastMCP interface.
"""
from datetime import datetime, timezone

from investorai_mcp.server import mcp
from investorai_mcp.stocks import SUPPORTED_TICKERS


# ── Pure sync helper (importable and unit-testable) ───────────────────────

def handle_meta_question(question: str) -> dict | None:
    """Answer a meta/capability question about the system.

    Returns a response dict when the question is about system capabilities,
    or None when the question is about actual market data.

    Performance / comparison questions (best, worst, return, rank …) are
    never short-circuited here — they are forwarded to the data pipeline.
    """
    q = question.lower()
    today = datetime.now(timezone.utc).date()

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

    # Supported sectors
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

    # Supported stocks / tickers
    if not _is_performance_q and any(kw in q for kw in [
        "what stock", "which stock", "stocks do you", "tickers",
        "what do you cover", "what do you support", "what can you",
        "supported stock", "available stock",
    ]):
        sectors2: dict[str, list[str]] = {}
        for sym, info in SUPPORTED_TICKERS.items():
            sectors2.setdefault(info["sector"], []).append(sym)
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


# ── MCP tool wrapper ──────────────────────────────────────────────────────

@mcp.tool()
async def get_system_info(question: str) -> dict:
    """Answer questions about what stocks and data this system supports.

    Handles questions like:
    - "What stocks do you support?"
    - "What sectors do you cover?"
    - "How far back does your data go?"
    - "What is today's date?"

    Returns:
        matched:           True if this is a capability question with an answer
        summary:           The answer (present when matched=True)
        citations:         [] — meta answers have no data citations
        validation_passed: True
    """
    result = handle_meta_question(question)
    if result is None:
        return {"matched": False}
    return {"matched": True, **result}
