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
                "Use to confirm a ticker is supported and get context before fetching price data."
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
                "Return pre-computed statistics for a stock: period return %, start/end price, "
                "high, low, volatility, trading days. Pure DB lookup — no LLM, very fast. "
                "Use this for performance comparisons and ranking. "
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
                "Return daily OHLCV price history for a supported stock. "
                "Use adj_close for trend analysis — adjusted for splits and dividends. "
                "Use when you need the full price series, not just summary stats."
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
                "Return AI-scored news sentiment for a stock: positive / negative / neutral, "
                "score (-1, 0, 1), one-sentence reasoning, and key themes. "
                "Use when the user asks about market sentiment or news tone."
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
                "Return data freshness status for a stock: last fetch time, staleness, error counts. "
                "Use only when the user asks about data freshness or to diagnose outdated data."
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
                "Force a live data refresh for a stock, bypassing the cache TTL. "
                "Only call when the user explicitly requests fresh data. "
                "Rate-limited to once per 5 minutes per ticker."
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

## Tool usage strategy

**Step 1 — Understand the question**
- Call `parse_question` first. It extracts ticker symbols, sector, and time range from natural language.
- If the user mentions a company name and you are unsure of the symbol, call `search_ticker`.
- For "all stocks" or sector-wide questions, call `get_system_info` to get the full symbol list.

**Step 2 — Fetch the right data**
- Performance / ranking questions → `get_daily_summary` (fast, pure DB, no LLM)
- Price trend questions → `get_price_history`
- News / events questions → `get_news`
- Sentiment questions → `get_sentiment`
- Company context → `get_stock_info`
- **Call tools for multiple stocks in a single turn** — return all tool_calls at once, do not make one call per turn.

**Step 3 — Write the answer**
- Synthesize data from tool results into a clear, grounded response.
- State exact numbers from tool results. Never invent figures.
- Cite the time range for every statistic you mention.
- For rankings, sort by period_return_pct descending and show the top results clearly.

## Rules
- Never guess ticker symbols.
- Never make up prices, returns, or statistics.
- Do not answer questions about stocks outside the supported universe.
- Keep answers concise and factual."""


# ---------------------------------------------------------------------------
# ReAct loop
# ---------------------------------------------------------------------------

async def _execute_tool_call(tc, api_key: str | None) -> tuple[str, str]:
    """Execute one tool call and return (tool_call_id, result_json)."""
    tool_name = tc.function.name
    try:
        tool_args = json.loads(tc.function.arguments)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse tool arguments for %s: %r", tool_name, tc.function.arguments)
        tool_args = {}

    logger.info("Agent tool: %s %s", tool_name, tool_args)

    try:
        result = await _dispatch(tool_name, tool_args, api_key)
        return tc.id, json.dumps(result, default=str)
    except Exception as e:
        logger.warning("Tool %s failed: %s", tool_name, e)
        return tc.id, json.dumps({"error": True, "message": str(e)})


async def run_agent_loop(
    question: str,
    history: list[dict] | None = None,
    api_key: str | None = None,
    session_hash: str = "anonymous",
    max_iterations: int = MAX_ITERATIONS,
) -> str:
    """
    Run the agentic ReAct loop and return the final text response.

    Each iteration:
      1. Call LLM with current messages + tool schemas
      2. If LLM returns tool_calls → execute ALL concurrently, append results, repeat
      3. If LLM returns text → done
    """
    # _call_llm_raw (not call_llm) is used here because the agent loop needs access
    # to tool_calls on the raw response object. call_llm is a text-only convenience
    # wrapper around _call_llm_raw. Both paths share the same Langfuse tracing and
    # DB usage logging — observability is identical.
    from investorai_mcp.llm.litellm_client import _call_llm_raw
    from investorai_mcp.llm.history import compress_history

    messages: list[dict] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    if history:
        compressed = await compress_history(history, session_hash=session_hash, api_key=api_key)
        messages.extend(compressed)
    messages.append({"role": "user", "content": question})

    for iteration in range(max_iterations):
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

        # No tool calls — LLM is done
        if not msg.tool_calls:
            return msg.content or ""

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
            [tc.function.name for tc in msg.tool_calls],
        )

        for tool_call_id, result_str in results:
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result_str,
            })

    logger.warning("Agent loop hit max_iterations (%d)", max_iterations)
    return "I reached the maximum number of tool calls without completing. Please try a more specific question."
