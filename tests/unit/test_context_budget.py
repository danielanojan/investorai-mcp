"""Tests for investorai_mcp/llm/context_budget.py"""

import json

# ── trim_tool_result ──────────────────────────────────────────────────────────


def test_trim_passthrough_when_under_budget():
    from investorai_mcp.llm.context_budget import trim_tool_result

    small = json.dumps({"symbol": "AAPL", "range": "1Y", "return_pct": 12.5})
    assert trim_tool_result("get_price_history", small) == small


def test_trim_price_history_drops_prices_array():
    from investorai_mcp.llm.context_budget import trim_tool_result

    payload = {
        "symbol": "AAPL",
        "range": "1Y",
        "start_price": 150.0,
        "end_price": 180.0,
        "period_return_pct": 20.0,
        "prices": [{"date": "2024-01-01", "price": 150.0}] * 500,
    }
    result_str = json.dumps(payload)
    trimmed = trim_tool_result("get_price_history", result_str, budget_tokens=100)
    result = json.loads(trimmed)
    assert "prices" not in result
    assert result["symbol"] == "AAPL"
    assert result["period_return_pct"] == 20.0


def test_trim_price_history_batch_drops_prices_per_symbol():
    from investorai_mcp.llm.context_budget import trim_tool_result

    prices_data = [{"date": "2024-01-01", "price": 150.0}] * 300
    payload = {
        "results": {
            "AAPL": {"symbol": "AAPL", "start_price": 150.0, "prices": prices_data},
            "MSFT": {"symbol": "MSFT", "start_price": 300.0, "prices": prices_data},
        },
        "range": "1Y",
    }
    result_str = json.dumps(payload)
    trimmed = trim_tool_result("get_price_history_batch", result_str, budget_tokens=200)
    result = json.loads(trimmed)
    for sym_data in result["results"].values():
        assert "prices" not in sym_data


def test_trim_price_batch_caps_at_30_symbols():
    from investorai_mcp.llm.context_budget import trim_tool_result

    symbols = {f"SYM{i:02d}": {"symbol": f"SYM{i:02d}", "prices": [1] * 100} for i in range(50)}
    payload = {"results": symbols, "range": "5Y"}
    result_str = json.dumps(payload)
    # budget=2000 — large enough to hold 30 trimmed symbols (~375 tokens), forces trimming
    trimmed = trim_tool_result("get_price_history_batch", result_str, budget_tokens=2000)
    result = json.loads(trimmed)
    assert len(result["results"]) == 30
    assert "note" in result


def test_trim_news_drops_ai_summary_and_url():
    from investorai_mcp.llm.context_budget import trim_tool_result

    articles = [
        {
            "headline": "AAPL rises",
            "source": "Reuters",
            "url": "https://example.com/long/path",
            "ai_summary": "A very long AI generated summary " * 50,
            "sentiment_score": 1,
            "published_at": "2024-01-15",
        }
    ] * 20
    payload = {"symbol": "AAPL", "articles": articles}
    result_str = json.dumps(payload)
    # budget=2000 — large enough to hold trimmed articles (~400 tokens), forces trimming
    trimmed = trim_tool_result("get_news", result_str, budget_tokens=2000)
    result = json.loads(trimmed)
    for article in result["articles"]:
        assert "ai_summary" not in article
        assert "url" not in article
        assert "headline" in article
        assert "sentiment_score" in article


def test_trim_news_batch_caps_5_articles_per_symbol():
    from investorai_mcp.llm.context_budget import trim_tool_result

    article = {
        "headline": "Stock news",
        "source": "BBC",
        "url": "https://bbc.com",
        "ai_summary": "summary " * 100,
        "sentiment_score": 0,
        "published_at": "2024-01-15",
    }
    payload = {
        "results": {
            "AAPL": {"articles": [article] * 10},
            "MSFT": {"articles": [article] * 10},
        }
    }
    result_str = json.dumps(payload)
    # budget=2000 — large enough to hold 2 symbols × 5 trimmed articles (~200 tokens)
    trimmed = trim_tool_result("get_news_batch", result_str, budget_tokens=2000)
    result = json.loads(trimmed)
    for sym_data in result["results"].values():
        assert len(sym_data["articles"]) == 5
        for a in sym_data["articles"]:
            assert "ai_summary" not in a


def test_trim_unknown_tool_truncates_raw_string():
    from investorai_mcp.llm.context_budget import trim_tool_result

    big = '{"data": "' + "x" * 100_000 + '"}'
    trimmed = trim_tool_result("unknown_tool", big, budget_tokens=100)
    assert len(trimmed) <= 100 * 4 + 50  # budget chars + small suffix


def test_trim_invalid_json_truncates_safely():
    from investorai_mcp.llm.context_budget import trim_tool_result

    bad = "not valid json " * 10_000
    trimmed = trim_tool_result("get_price_history", bad, budget_tokens=50)
    assert "[truncated" in trimmed
    assert len(trimmed) < len(bad)


# ── prune_messages ────────────────────────────────────────────────────────────


def test_prune_removes_oldest_tool_messages():
    from investorai_mcp.llm.context_budget import prune_messages

    big_content = "x" * 40_000  # ~10K tokens each
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "thinking"},
        {"role": "tool", "tool_call_id": "1", "content": big_content},
        {"role": "tool", "tool_call_id": "2", "content": big_content},
        {"role": "tool", "tool_call_id": "3", "content": big_content},
    ]
    pruned, dropped = prune_messages(messages, target_tokens=15_000)
    assert dropped > 0
    # Tool messages should be gone first
    tool_count = sum(1 for m in pruned if m["role"] == "tool")
    assert tool_count < 3


def test_prune_never_removes_system_user_assistant():
    from investorai_mcp.llm.context_budget import prune_messages

    big_content = "x" * 100_000
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "assistant turn"},
        {"role": "tool", "tool_call_id": "1", "content": big_content},
    ]
    pruned, dropped = prune_messages(messages, target_tokens=100)
    roles = {m["role"] for m in pruned}
    assert "system" in roles
    assert "user" in roles
    assert "assistant" in roles


def test_prune_returns_zero_dropped_when_under_target():
    from investorai_mcp.llm.context_budget import prune_messages

    messages = [
        {"role": "system", "content": "short"},
        {"role": "user", "content": "question"},
    ]
    pruned, dropped = prune_messages(messages, target_tokens=10_000)
    assert dropped == 0
    assert len(pruned) == len(messages)


def test_prune_stops_when_no_tool_messages_remain():
    from investorai_mcp.llm.context_budget import prune_messages

    big = "x" * 400_000  # ~100K tokens
    messages = [
        {"role": "system", "content": big},
        {"role": "user", "content": big},
    ]
    pruned, dropped = prune_messages(messages, target_tokens=100)
    # Can't drop system/user — should stop and return what it has
    assert dropped == 0
    assert len(pruned) == 2


# ── count_tokens_approx fix ───────────────────────────────────────────────────


def test_count_tokens_includes_tool_calls():
    from investorai_mcp.llm.history import count_tokens_approx

    tool_calls = [
        {"id": "tc1", "function": {"name": "get_prices", "arguments": '{"symbol":"AAPL"}'}}
    ]
    messages_with = [{"role": "assistant", "content": "", "tool_calls": tool_calls}]
    messages_without = [{"role": "assistant", "content": ""}]
    assert count_tokens_approx(messages_with) > count_tokens_approx(messages_without)


def test_count_tokens_handles_none_content():
    from investorai_mcp.llm.history import count_tokens_approx

    messages = [{"role": "assistant", "content": None, "tool_calls": []}]
    assert count_tokens_approx(messages) == 0
