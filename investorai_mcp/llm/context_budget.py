import json
import logging

logger = logging.getLogger(__name__)

_NEWS_KEEP = frozenset({"headline", "source", "sentiment_score", "published_at"})
_PRICE_DROP = frozenset({"prices"})


def _approx_tokens(s: str) -> int:
    return len(s) // 4


def trim_tool_result(tool_name: str, result_str: str, budget_tokens: int = 8000) -> str:
    """Trim a serialized tool result to fit within budget_tokens.

    Called before each result is appended to the agent's message list.
    Returns the original string unchanged if already within budget.
    """
    if _approx_tokens(result_str) <= budget_tokens:
        return result_str

    try:
        result = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        max_chars = budget_tokens * 4
        return result_str[:max_chars] + " ...[truncated to fit context]"

    if tool_name in ("get_price_history", "get_price_history_batch"):
        result = _trim_price(result, tool_name)
    elif tool_name in ("get_news", "get_news_batch"):
        result = _trim_news(result, tool_name)

    trimmed = json.dumps(result)
    if _approx_tokens(trimmed) > budget_tokens:
        return json.dumps(
            {"truncated": True, "reason": "result exceeded context budget after trimming"}
        )
    return trimmed


def _trim_price(result: dict, tool_name: str) -> dict:
    if tool_name == "get_price_history":
        return {k: v for k, v in result.items() if k not in _PRICE_DROP}

    if "results" not in result:
        return result

    symbols = list(result["results"].keys())
    if len(symbols) > 30:
        result["note"] = f"Trimmed to 30/{len(symbols)} symbols to fit context window."
        symbols = symbols[:30]

    result["results"] = {
        sym: {k: v for k, v in result["results"][sym].items() if k not in _PRICE_DROP}
        for sym in symbols
    }
    return result


def _trim_news(result: dict, tool_name: str) -> dict:
    def _slim(article: dict) -> dict:
        return {k: v for k, v in article.items() if k in _NEWS_KEEP}

    if tool_name == "get_news":
        if "articles" in result:
            result["articles"] = [_slim(a) for a in result["articles"]]
        return result

    if "results" not in result:
        return result

    for sym_data in result["results"].values():
        if "articles" in sym_data:
            sym_data["articles"] = [_slim(a) for a in sym_data["articles"][:5]]
    return result


def prune_messages(messages: list[dict], target_tokens: int) -> tuple[list[dict], int]:
    """Drop oldest role=tool messages until total tokens are under target_tokens.

    Never removes system, user, or assistant messages.
    Returns (pruned_list, count_dropped).
    """

    def _count(msgs: list[dict]) -> int:
        total = 0
        for m in msgs:
            total += len(m.get("content") or "")
            if m.get("tool_calls"):
                total += len(json.dumps(m["tool_calls"]))
        return total // 4

    result = list(messages)
    dropped = 0

    while _count(result) > target_tokens:
        tool_idx = next(
            (i for i, m in enumerate(result) if m.get("role") == "tool"),
            None,
        )
        if tool_idx is None:
            break
        result.pop(tool_idx)
        dropped += 1

    return result, dropped
