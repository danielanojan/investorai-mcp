"""
Lightweight query router — classifies user questions without an LLM call.

Categories:
  meta         — "what can you do?", "which stocks supported?" → no data fetch needed
  single_stock — question about exactly one ticker
  multi_stock  — question comparing a few specific tickers (2–9 detected)
  broad        — all/sector/every → many tickers, use batch tools + trim aggressively

Classification is best-effort. If wrong, the agent has full tool access and will
self-correct via parse_question. The hint is a nudge, not a hard constraint.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from investorai_mcp.stocks import SUPPORTED_TICKERS


class QueryType(StrEnum):
    META = "meta"
    SINGLE_STOCK = "single_stock"
    MULTI_STOCK = "multi_stock"
    BROAD = "broad"


@dataclass(frozen=True)
class QueryClass:
    type: QueryType
    symbols: tuple[str, ...]
    hint: str


_META_RE = re.compile(
    r"\b(what can you|what do you|how does this|which stocks|what stocks|"
    r"supported|universe|help|capabilities|features|available stocks)\b",
    re.IGNORECASE,
)

_BROAD_RE = re.compile(
    r"\b(all\s+stocks?|all\s+\d+|every\s+stock|by\s+sector|sector\b|entire\s+universe|"
    r"across\s+(all|the\s+\w+)|compare\s+all|rank\s+all|"
    r"best\s+(overall|across)|worst\s+(overall|across))\b",
    re.IGNORECASE,
)


def _detect_symbols(question: str) -> list[str]:
    """Return known ticker symbols found in the question (word-boundary match, uppercase)."""
    words = re.findall(r"\b[A-Z]{1,5}\b", question.upper())
    seen: dict[str, None] = {}
    for w in words:
        if w in SUPPORTED_TICKERS and w not in seen:
            seen[w] = None
    return list(seen)


def classify(question: str) -> QueryClass:
    """Classify a user question into a QueryType.

    Pure function — no I/O, no LLM call. Safe to call before the agent loop.
    Returns a QueryClass with a routing hint to inject into the system prompt.
    """
    if _META_RE.search(question):
        return QueryClass(
            type=QueryType.META,
            symbols=(),
            hint=(
                "[Router: meta query] Call get_system_info to answer. No price or news data needed."
            ),
        )

    if _BROAD_RE.search(question):
        return QueryClass(
            type=QueryType.BROAD,
            symbols=(),
            hint=(
                "[Router: broad query across many stocks] "
                "Use batch tools (get_daily_summary_batch, get_price_history_batch, "
                "get_news_batch). Expect trimmed results — reason from summary stats, "
                "not raw prices."
            ),
        )

    symbols = _detect_symbols(question)
    n = len(symbols)

    if n == 1:
        return QueryClass(
            type=QueryType.SINGLE_STOCK,
            symbols=(symbols[0],),
            hint=(
                f"[Router: single-stock query about {symbols[0]}] "
                "Use targeted (non-batch) tools only."
            ),
        )

    if n >= 2:
        capped = symbols[:9]
        sym_str = ", ".join(capped)
        return QueryClass(
            type=QueryType.MULTI_STOCK,
            symbols=tuple(capped),
            hint=(
                f"[Router: multi-stock query comparing {sym_str}] "
                "Use batch tools with exactly these symbols."
            ),
        )

    # No symbols detected — likely single stock referred to by name
    return QueryClass(
        type=QueryType.SINGLE_STOCK,
        symbols=(),
        hint=(
            "[Router: single-stock query, ticker not pre-detected] "
            "Call parse_question first to identify the ticker symbol."
        ),
    )
