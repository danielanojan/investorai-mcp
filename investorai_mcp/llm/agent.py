"""
Agentic loop for the BYOK chat endpoint.

Implements a ReAct (Reason + Act) loop:
  1. LLM receives user question + primitive tool schemas
  2. LLM decides which tool(s) to call — can call many in parallel in one turn
  3. Server executes all tool calls concurrently (asyncio.gather)
  4. Results fed back to LLM
  5. Repeat until LLM produces a final text response (no more tool calls)

The LLM drives all orchestration and writes the final narrative directly.
get_trend_summary is intentionally excluded — it is a fat convenience tool
for MCP clients (Claude Desktop / Code) that handles everything internally.
The agent loop uses primitive tools so the LLM reasons about each step.
"""

import asyncio
import json
import logging
from typing import Any

# Approximate token limits — ~4 chars per token. Hard limit aborts the loop;
# warn limit logs but continues so small overages don't break valid queries.
_TOKEN_HARD_LIMIT = 180_000
_TOKEN_WARN_LIMIT = 150_000

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 8

# ---------------------------------------------------------------------------
# Tool schemas — primitive tools only, OpenAI function-calling format
# get_trend_summary deliberately excluded: it embeds its own LLM call and
# hardcodes orchestration. Agent LLM fetches primitives and narrates itself.
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "parse_question",
            "description": (
                "Parse a natural language question and extract: detected ticker symbols, "
                "sector, time range, and resolved date references. "
                "Call this first for any market question to know what data to fetch."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The user's natural language question.",
                    }
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": (
                "Return meta information: full list of all 50 supported ticker symbols grouped by sector, "
                "today's date, and supported time ranges. "
                "Use this when the user asks which stocks are supported, or when you need "
                "the complete symbol list for a broad comparison query."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The user's meta question.",
                    }
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_ticker",
            "description": (
                "Search for supported stock tickers by company name, keyword, sector, or symbol. "
                "Use this when the user mentions a company name or partial symbol and you are unsure "
                "of the exact ticker. Never guess ticker symbols."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Company name, ticker symbol, sector, or concept.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_info",
            "description": (
                "Return company profile: name, sector, exchange, market cap, currency. "
                "Use when you need company context before fetching price or news data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker_symbol": {
                        "type": "string",
                        "description": "Uppercase ticker symbol, e.g. 'AAPL'.",
                    }
                },
                "required": ["ticker_symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_daily_summary",
            "description": (
                "Return performance statistics for a stock: period return %, start/end price, "
                "high, low, volatility, trading days. "
                "Use for performance comparisons and ranking. "
                "For broad comparisons call this for all relevant stocks in one turn."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker_symbol": {
                        "type": "string",
                        "description": "Uppercase ticker symbol, e.g. 'AAPL'.",
                    },
                    "range": {
                        "type": "string",
                        "enum": ["1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"],
                        "description": "Time range for statistics. Default: '1Y'.",
                    },
                },
                "required": ["ticker_symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_price_history",
            "description": (
                "Return daily price history for a supported stock. "
                "Use adj_close for trend analysis — adjusted for splits and dividends. "
                "Use when you need the actual price series, not just summary stats. "
                "Always set limit=52 or less to keep the response concise."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker_symbol": {
                        "type": "string",
                        "description": "Uppercase ticker symbol, e.g. 'AAPL'.",
                    },
                    "range": {
                        "type": "string",
                        "enum": ["1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"],
                        "description": "Time range. Default: '1Y'.",
                    },
                    "price_type": {
                        "type": "string",
                        "enum": ["adj_close", "close", "avg_price"],
                        "description": "Price field to return. Default: 'adj_close'.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max price points to return, evenly sampled. Use 52 for yearly trends, 30 for monthly. Default 0 = all points (avoid for LLM use).",
                    },
                },
                "required": ["ticker_symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": (
                "Return recent news headlines for a supported stock. "
                "Use when the user asks about recent news, events, or what's happening with a stock."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker_symbol": {
                        "type": "string",
                        "description": "Uppercase ticker symbol, e.g. 'AAPL'.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of articles to return. Default: 10, max: 50.",
                    },
                },
                "required": ["ticker_symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sentiment",
            "description": (
                "Return news sentiment for a stock: positive / negative / neutral, "
                "score (-1, 0, 1), one-sentence reasoning, and key themes. "
                "Use when the user asks about market sentiment or news tone. "
                "Requires news to be cached — call get_news first if unsure."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker_symbol": {
                        "type": "string",
                        "description": "Uppercase ticker symbol, e.g. 'AAPL'.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of articles to score. Default: 10.",
                    },
                },
                "required": ["ticker_symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cache_status",
            "description": (
                "Return data freshness status for a stock: when each data type was last updated and whether it is current. "
                "Use only when the user asks about data freshness or reports outdated data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker_symbol": {
                        "type": "string",
                        "description": "Uppercase ticker symbol, e.g. 'AAPL'.",
                    }
                },
                "required": ["ticker_symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "refresh_ticker",
            "description": (
                "Force a live data update for a stock. "
                "Only call when the user explicitly requests fresh or up-to-date data. "
                "Can only be called once per 5 minutes per ticker."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker_symbol": {
                        "type": "string",
                        "description": "Uppercase ticker symbol, e.g. 'AAPL'.",
                    }
                },
                "required": ["ticker_symbol"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Tool dispatcher
# api_key injected here — never exposed in tool schemas
# ---------------------------------------------------------------------------

async def _dispatch(tool_name: str, tool_args: dict, api_key: str | None) -> Any:
    if tool_name == "parse_question":
        from investorai_mcp.tools.parse_question import parse_question
        return await parse_question(**tool_args)

    if tool_name == "get_system_info":
        from investorai_mcp.tools.get_system_info import get_system_info
        return await get_system_info(**tool_args)

    if tool_name == "search_ticker":
        from investorai_mcp.tools.search_ticker import search_ticker
        return await search_ticker(**tool_args)

    if tool_name == "get_stock_info":
        from investorai_mcp.tools.get_stock_info import get_stock_info
        return await get_stock_info(**tool_args)

    if tool_name == "get_daily_summary":
        from investorai_mcp.tools.get_daily_summary import get_daily_summary
        return await get_daily_summary(**tool_args)

    if tool_name == "get_price_history":
        from investorai_mcp.tools.get_price_history import get_price_history
        return await get_price_history(**tool_args)

    if tool_name == "get_news":
        from investorai_mcp.tools.get_news import get_news
        return await get_news(**tool_args)

    if tool_name == "get_sentiment":
        from investorai_mcp.tools.get_sentiment import get_sentiment
        return await get_sentiment(**tool_args, api_key=api_key)

    if tool_name == "get_cache_status":
        from investorai_mcp.tools.get_cache_status import get_cache_status
        return await get_cache_status(**tool_args)

    if tool_name == "refresh_ticker":
        from investorai_mcp.tools.refresh_ticker import refresh_ticker
        return await refresh_ticker(**tool_args)

    raise ValueError(f"Unknown tool: {tool_name}")


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

AGENT_SYSTEM_PROMPT = """You are a stock research assistant for retail investors. You have access to data for 50 curated blue-chip stocks across 5 sectors: Technology, Finance, Healthcare, Consumer, Energy & Industrials.

## Tool usage — follow these steps in order

**Step 1 — Always call `parse_question` first.**
Do not skip this. It extracts ticker symbols, sector, and time range from the user's question.
- If the user mentions a company name and you are unsure of the exact ticker, also call `search_ticker`.
- For "all stocks" or sector-wide questions, also call `get_system_info` to get the full symbol list.

**Step 2 — Fetch data. Call ALL required tools in a single turn.**
Do not make one tool call per turn. Return all tool_calls at once — they execute in parallel.
- Performance / ranking → `get_daily_summary`
- Price trends → `get_price_history` (set limit=52 or less)
- News / recent events → `get_news`
- Sentiment → `get_news` first, then `get_sentiment` (sentiment requires cached news)
- Company profile → `get_stock_info`

**Step 3 — Write the answer directly from tool results.**
- State exact numbers from tool results. Never invent or estimate figures.
- Cite the time range for every statistic you mention.
- For rankings, sort by period_return_pct descending and show top results clearly.
- Stop after one answer — do not call more tools unless the user asks a follow-up.

## Hard rules
- Only use the tools listed above. Do not call tools that are not in this list.
- Never guess ticker symbols. Use `search_ticker` if unsure.
- Never make up prices, returns, or statistics.
- Do not answer questions about stocks outside the 50-stock supported universe.
- If a tool returns `"error": true`, read the message and either retry with corrected arguments or tell the user what went wrong."""


# ---------------------------------------------------------------------------
# ReAct loop
# ---------------------------------------------------------------------------

async def _execute_tool_call(tc, api_key: str | None) -> tuple[str, str]:
    """Execute one tool call and return (tool_call_id, result_json)."""
    tool_name = tc.function.name

    # Return parse error directly — don't call tool with empty args
    try:
        tool_args = json.loads(tc.function.arguments)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse tool arguments for %s: %r", tool_name, tc.function.arguments)
        return tc.id, json.dumps({
            "error": True,
            "code": "INVALID_TOOL_ARGS",
            "message": f"Could not parse arguments for {tool_name}. Try again with valid JSON arguments.",
            "retryable": True,
        })

    logger.info("Agent tool: %s %s", tool_name, tool_args)

    try:
        result = await _dispatch(tool_name, tool_args, api_key)
        return tc.id, json.dumps(result, default=str)
    except TimeoutError:
        logger.warning("Tool %s timed out", tool_name)
        return tc.id, json.dumps({
            "error": True, "code": "TIMEOUT",
            "message": f"{tool_name} timed out. Try again or use a smaller date range.",
            "retryable": True,
        })
    except ValueError as e:
        logger.warning("Tool %s bad arguments: %s", tool_name, e)
        return tc.id, json.dumps({
            "error": True, "code": "BAD_ARGS",
            "message": str(e),
            "retryable": False,
        })
    except Exception as e:
        logger.warning("Tool %s failed: %s", tool_name, e)
        return tc.id, json.dumps({
            "error": True, "code": "TOOL_ERROR",
            "message": str(e),
            "retryable": True,
        })


async def run_agent_loop(
    question: str,
    history: list[dict] | None = None,
    api_key: str | None = None,
    session_hash: str = "anonymous",
    max_iterations: int = MAX_ITERATIONS,
):
    """
    Async generator — yields SSE event dicts as the agent executes.

    Event types:
      {"type": "thinking", "tools": [...], "iteration": N}  — LLM issued tool calls
      {"type": "token",    "content": "word "}               — final answer words
      {"type": "done"}                                        — stream complete

    Each iteration:
      1. Call LLM with current messages + tool schemas
      2. If LLM returns tool_calls → yield thinking event, execute concurrently, repeat
      3. If LLM returns text → yield token events word by word, yield done
    """
    # _call_llm_raw (not call_llm) is used here because the agent loop needs access
    # to tool_calls on the raw response object. call_llm is a text-only convenience
    # wrapper around _call_llm_raw. Both paths share the same Langfuse tracing and
    # DB usage logging — observability is identical.
    from investorai_mcp.llm.history import compress_history, count_tokens_approx
    from investorai_mcp.llm.litellm_client import _call_llm_raw

    messages: list[dict] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    if history:
        compressed = await compress_history(history, session_hash=session_hash, api_key=api_key)
        messages.extend(compressed)
    messages.append({"role": "user", "content": question})

    for iteration in range(max_iterations):
        token_estimate = count_tokens_approx(messages)
        if token_estimate > _TOKEN_HARD_LIMIT:
            logger.error("Agent context too large (~%d tokens), aborting loop", token_estimate)
            yield {"type": "token", "content": "The query requires too much data to process. Please ask about fewer stocks or a shorter time range."}
            yield {"type": "done"}
            return
        if token_estimate > _TOKEN_WARN_LIMIT:
            logger.warning("Agent context large: ~%d tokens at iteration %d", token_estimate, iteration + 1)

        response = await _call_llm_raw(
            messages=messages,
            session_hash=session_hash,
            tool_name="agent_loop",
            max_tokens=2000,
            api_key=api_key,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )

        msg = response.choices[0].message

        # No tool calls — LLM has final answer, stream it word by word
        if not msg.tool_calls:
            final_text = msg.content or ""
            words = final_text.split(" ")
            for i, word in enumerate(words):
                yield {"type": "token", "content": word + (" " if i < len(words) - 1 else "")}
            yield {"type": "done"}
            return

        # Yield thinking event so client knows what tools are running
        tool_names = [tc.function.name for tc in msg.tool_calls]
        yield {"type": "thinking", "tools": tool_names, "iteration": iteration + 1}

        # Append assistant turn with all tool_calls
        messages.append(msg.model_dump(exclude_unset=True))

        # Execute all tool calls in this turn concurrently
        results = await asyncio.gather(
            *[_execute_tool_call(tc, api_key) for tc in msg.tool_calls]
        )

        logger.info(
            "Iteration %d: executed %d tool call(s): %s",
            iteration + 1,
            len(msg.tool_calls),
            tool_names,
        )

        for tool_call_id, result_str in results:
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result_str,
            })

    logger.warning("Agent loop hit max_iterations (%d)", max_iterations)
    yield {"type": "token", "content": "I reached the maximum number of tool calls without completing. Please try a more specific question."}
    yield {"type": "done"}
