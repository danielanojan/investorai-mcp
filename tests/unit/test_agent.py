"""Unit tests for the ReAct agent loop (llm/agent.py).

Patch targets — imports inside run_agent_loop are local, so patch the source:
  _call_llm_raw    → investorai_mcp.llm.litellm_client._call_llm_raw
  compress_history → investorai_mcp.llm.history.compress_history
  count_tokens_approx → investorai_mcp.llm.history.count_tokens_approx

Module-level names in agent.py patch at:
  _dispatch        → investorai_mcp.llm.agent._dispatch
  _TOKEN_HARD_LIMIT / _TOKEN_WARN_LIMIT → investorai_mcp.llm.agent.*
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Patch paths
# ---------------------------------------------------------------------------
_LLM_RAW   = "investorai_mcp.llm.litellm_client._call_llm_raw"
_COMPRESS  = "investorai_mcp.llm.history.compress_history"
_COUNT_TOK = "investorai_mcp.llm.history.count_tokens_approx"
_DISPATCH  = "investorai_mcp.llm.agent._dispatch"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(content: str = "", tool_calls=None):
    """Build a minimal LiteLLM-style response object."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    msg.model_dump = MagicMock(return_value={"role": "assistant", "content": content})

    choice = MagicMock()
    choice.message = msg

    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _make_tool_call(name: str, args: dict, call_id: str = "tc_1"):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


async def _collect(gen):
    """Drain an async generator into a list."""
    return [event async for event in gen]


# ---------------------------------------------------------------------------
# Final answer (no tool calls)
# ---------------------------------------------------------------------------

async def test_final_answer_yields_tokens_and_done():
    from investorai_mcp.llm.agent import run_agent_loop

    response = _make_response("Hello world")
    with patch(_LLM_RAW, new=AsyncMock(return_value=response)), \
         patch(_COMPRESS, new=AsyncMock(return_value=[])), \
         patch(_COUNT_TOK, return_value=1000):
        events = await _collect(run_agent_loop("hi"))

    types = [e["type"] for e in events]
    assert "token" in types
    assert types[-1] == "done"
    full_text = "".join(e["content"] for e in events if e["type"] == "token")
    assert "Hello" in full_text
    assert "world" in full_text


async def test_empty_content_yields_done():
    from investorai_mcp.llm.agent import run_agent_loop

    response = _make_response("")
    with patch(_LLM_RAW, new=AsyncMock(return_value=response)), \
         patch(_COMPRESS, new=AsyncMock(return_value=[])), \
         patch(_COUNT_TOK, return_value=1000):
        events = await _collect(run_agent_loop("hi"))

    assert events[-1]["type"] == "done"


# ---------------------------------------------------------------------------
# Tool-call path
# ---------------------------------------------------------------------------

async def test_tool_call_yields_thinking_then_done():
    from investorai_mcp.llm.agent import run_agent_loop

    tc = _make_tool_call("get_price_history", {"ticker_symbol": "AAPL", "range": "1Y"})
    first_response  = _make_response(tool_calls=[tc])
    final_response  = _make_response("AAPL is up.")

    call_count = 0

    async def fake_llm(**kwargs):
        nonlocal call_count
        call_count += 1
        return first_response if call_count == 1 else final_response

    tool_result = {"symbol": "AAPL", "prices": [], "is_stale": False}

    with patch(_LLM_RAW, new=fake_llm), \
         patch(_COMPRESS, new=AsyncMock(return_value=[])), \
         patch(_COUNT_TOK, return_value=1000), \
         patch(_DISPATCH, new=AsyncMock(return_value=tool_result)):
        events = await _collect(run_agent_loop("What is AAPL?"))

    thinking_events = [e for e in events if e["type"] == "thinking"]
    assert len(thinking_events) == 1
    assert "get_price_history" in thinking_events[0]["tools"]
    assert events[-1]["type"] == "done"


async def test_thinking_event_contains_iteration_number():
    from investorai_mcp.llm.agent import run_agent_loop

    tc = _make_tool_call("search_ticker", {"query": "apple"})
    first_response = _make_response(tool_calls=[tc])
    final_response = _make_response("Done.")

    call_count = 0

    async def fake_llm(**kwargs):
        nonlocal call_count
        call_count += 1
        return first_response if call_count == 1 else final_response

    with patch(_LLM_RAW, new=fake_llm), \
         patch(_COMPRESS, new=AsyncMock(return_value=[])), \
         patch(_COUNT_TOK, return_value=1000), \
         patch(_DISPATCH, new=AsyncMock(return_value={"symbol": "AAPL"})):
        events = await _collect(run_agent_loop("find apple"))

    thinking = [e for e in events if e["type"] == "thinking"]
    assert thinking[0]["iteration"] == 1


# ---------------------------------------------------------------------------
# Max iterations
# ---------------------------------------------------------------------------

async def test_max_iterations_yields_error_token():
    from investorai_mcp.llm.agent import run_agent_loop

    tc = _make_tool_call("get_price_history", {"ticker_symbol": "AAPL"})
    always_tool_response = _make_response(tool_calls=[tc])

    with patch(_LLM_RAW, new=AsyncMock(return_value=always_tool_response)), \
         patch(_COMPRESS, new=AsyncMock(return_value=[])), \
         patch(_COUNT_TOK, return_value=1000), \
         patch(_DISPATCH, new=AsyncMock(return_value={})):
        events = await _collect(run_agent_loop("loop forever", max_iterations=3))

    assert events[-1]["type"] == "done"
    token_text = "".join(e["content"] for e in events if e["type"] == "token")
    assert "maximum" in token_text.lower() or "limit" in token_text.lower()


# ---------------------------------------------------------------------------
# Token budget
# ---------------------------------------------------------------------------

async def test_token_hard_limit_aborts_loop():
    from investorai_mcp.llm.agent import _TOKEN_HARD_LIMIT, run_agent_loop

    mock_llm = AsyncMock()
    with patch(_LLM_RAW, new=mock_llm), \
         patch(_COMPRESS, new=AsyncMock(return_value=[])), \
         patch(_COUNT_TOK, return_value=_TOKEN_HARD_LIMIT + 1):
        events = await _collect(run_agent_loop("big query"))

    mock_llm.assert_not_called()
    assert events[-1]["type"] == "done"
    token_text = "".join(e["content"] for e in events if e["type"] == "token")
    assert len(token_text) > 0


async def test_token_warn_limit_continues():
    from investorai_mcp.llm.agent import _TOKEN_WARN_LIMIT, run_agent_loop

    response = _make_response("Answer.")
    with patch(_LLM_RAW, new=AsyncMock(return_value=response)), \
         patch(_COMPRESS, new=AsyncMock(return_value=[])), \
         patch(_COUNT_TOK, return_value=_TOKEN_WARN_LIMIT + 1):
        events = await _collect(run_agent_loop("medium query"))

    assert events[-1]["type"] == "done"
    assert any(e["type"] == "token" for e in events)


# ---------------------------------------------------------------------------
# _execute_tool_call
# ---------------------------------------------------------------------------

async def test_execute_tool_call_bad_json_returns_error():
    from investorai_mcp.llm.agent import _execute_tool_call

    tc = MagicMock()
    tc.id = "tc_bad"
    tc.function.name = "get_price_history"
    tc.function.arguments = "{not valid json"

    call_id, result_str = await _execute_tool_call(tc, api_key=None)
    result = json.loads(result_str)

    assert result["error"] is True
    assert result["code"] == "INVALID_TOOL_ARGS"
    assert result["retryable"] is True


async def test_execute_tool_call_timeout_returns_retryable_error():
    from investorai_mcp.llm.agent import _execute_tool_call

    tc = _make_tool_call("get_price_history", {"ticker_symbol": "AAPL"})

    with patch(_DISPATCH, new=AsyncMock(side_effect=TimeoutError())):
        call_id, result_str = await _execute_tool_call(tc, api_key=None)

    result = json.loads(result_str)
    assert result["error"] is True
    assert result["code"] == "TIMEOUT"
    assert result["retryable"] is True


async def test_execute_tool_call_value_error_returns_non_retryable():
    from investorai_mcp.llm.agent import _execute_tool_call

    tc = _make_tool_call("get_price_history", {"ticker_symbol": "AAPL"})

    with patch(_DISPATCH, new=AsyncMock(side_effect=ValueError("bad range"))):
        call_id, result_str = await _execute_tool_call(tc, api_key=None)

    result = json.loads(result_str)
    assert result["error"] is True
    assert result["code"] == "BAD_ARGS"
    assert result["retryable"] is False


async def test_execute_tool_call_generic_error_is_retryable():
    from investorai_mcp.llm.agent import _execute_tool_call

    tc = _make_tool_call("get_news", {"ticker_symbol": "AAPL"})

    with patch(_DISPATCH, new=AsyncMock(side_effect=RuntimeError("network down"))):
        call_id, result_str = await _execute_tool_call(tc, api_key=None)

    result = json.loads(result_str)
    assert result["error"] is True
    assert result["retryable"] is True


async def test_execute_tool_call_success_returns_result():
    from investorai_mcp.llm.agent import _execute_tool_call

    tc = _make_tool_call("search_ticker", {"query": "apple"})
    tool_result = {"matches": [{"symbol": "AAPL"}]}

    with patch(_DISPATCH, new=AsyncMock(return_value=tool_result)):
        call_id, result_str = await _execute_tool_call(tc, api_key=None)

    assert call_id == "tc_1"
    result = json.loads(result_str)
    assert result["matches"][0]["symbol"] == "AAPL"


# ---------------------------------------------------------------------------
# History compression
# ---------------------------------------------------------------------------

async def test_history_is_compressed_before_loop():
    from investorai_mcp.llm.agent import run_agent_loop

    response = _make_response("Fine.")
    compressed = [{"role": "user", "content": "summary"}, {"role": "assistant", "content": "ok"}]
    mock_compress = AsyncMock(return_value=compressed)

    with patch(_LLM_RAW, new=AsyncMock(return_value=response)), \
         patch(_COMPRESS, new=mock_compress), \
         patch(_COUNT_TOK, return_value=1000):
        await _collect(run_agent_loop("question", history=[{"role": "user", "content": "old msg"}]))

    mock_compress.assert_called_once()


async def test_no_history_skips_compression():
    from investorai_mcp.llm.agent import run_agent_loop

    response = _make_response("Fine.")
    mock_compress = AsyncMock(return_value=[])

    with patch(_LLM_RAW, new=AsyncMock(return_value=response)), \
         patch(_COMPRESS, new=mock_compress), \
         patch(_COUNT_TOK, return_value=1000):
        await _collect(run_agent_loop("question", history=None))

    mock_compress.assert_not_called()


# ---------------------------------------------------------------------------
# Concurrent tool dispatch
# ---------------------------------------------------------------------------

async def test_multiple_tool_calls_dispatched_concurrently():
    from investorai_mcp.llm.agent import run_agent_loop

    tc1 = _make_tool_call("get_price_history", {"ticker_symbol": "AAPL"}, call_id="tc_1")
    tc2 = _make_tool_call("get_price_history", {"ticker_symbol": "MSFT"}, call_id="tc_2")
    first_response = _make_response(tool_calls=[tc1, tc2])
    final_response = _make_response("Both done.")

    call_count = 0

    async def fake_llm(**kwargs):
        nonlocal call_count
        call_count += 1
        return first_response if call_count == 1 else final_response

    dispatch_calls = []

    async def fake_dispatch(tool_name, tool_args, api_key):
        dispatch_calls.append(tool_name)
        return {"prices": []}

    with patch(_LLM_RAW, new=fake_llm), \
         patch(_COMPRESS, new=AsyncMock(return_value=[])), \
         patch(_COUNT_TOK, return_value=1000), \
         patch(_DISPATCH, new=fake_dispatch):
        events = await _collect(run_agent_loop("Compare AAPL and MSFT"))

    assert len(dispatch_calls) == 2
    assert "get_price_history" in dispatch_calls
    thinking = [e for e in events if e["type"] == "thinking"]
    assert len(thinking[0]["tools"]) == 2
