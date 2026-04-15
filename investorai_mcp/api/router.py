"""
FastAPI BFF - Backend and frontend

Rest layer consumeed by React Web UI. 
No business logic here - calls the same internal services
as the MCP tools

"""

import math
import time as _time
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from investorai_mcp.api.error_handler import make_error
from investorai_mcp.api.rate_limit import limiter
from investorai_mcp.stocks import SUPPORTED_TICKERS, is_supported

router = APIRouter()


async def _log_chat_request(
    question: str,
    symbols: str,
    range_: str,
    total_latency_ms: int,
    status: str,
) -> None:
    """Persist one chat call row to chat_request_log."""
    from investorai_mcp.db import AsyncSessionLocal
    from investorai_mcp.db.models import ChatRequestLog
    async with AsyncSessionLocal() as session:
        session.add(ChatRequestLog(
            question=question,
            symbols=symbols,
            range=range_,
            total_latency_ms=total_latency_ms,
            status=status,
            ts=datetime.now(timezone.utc),
        ))
        await session.commit()


def _percentile(sorted_values: list[int], p: float) -> int:
    """Return the p-th percentile from a pre-sorted list."""
    if not sorted_values:
        return 0
    idx = math.ceil(len(sorted_values) * p / 100) - 1
    return sorted_values[max(0, min(idx, len(sorted_values) - 1))]

#---- Health ------------------------------------------

@router.get("/health")
async def health():
    from investorai_mcp.config import settings
    return {
        "status": "ok",
        "version": "0.1.0",
        "transport": settings.mcp_transport, 
        "ai_enabled": settings.ai_chat_enabled,
        "provider": settings.data_provider, 
    }
    

# ---- Tickers ---------------------------------------

@router.get("/tickers")
async def list_tickers():
    return {
        "tickers": [
            {
                "symbol": symbol,
                "name": info["name"],
                "sector": info["sector"],
                "exchange": info["exchange"],       
            }
            for symbol, info in SUPPORTED_TICKERS.items()   
        ],
        "total": len(SUPPORTED_TICKERS),    
    }
    
@router.get("/tickers/search")
async def search_tickers(q: str = Query(..., min_length=1)):
    from investorai_mcp.tools.search_ticker import search_ticker
    result = await search_ticker(q)
    return result 

### ---- Stock data ---------------------------------------
@router.get("/stocks/{symbol}/prices")
@limiter.limit("120/minute")
async def get_prices(
    request: Request, 
    symbol: str,
    range: Literal["1W","1M","3M","6M","1Y","3Y","5Y"] = "1Y",
    price_type: Literal["adj_close","avg_price","close"] = "adj_close",
):
    symbol = symbol.upper()
    if not is_supported(symbol):
        return JSONResponse(
            status_code=404,
            content = make_error(
                "TICKER_NOT_SUPPORTED",
                f"Ticker '{symbol}' is not in supported universe.",
                "Use /tickers/search to find supported tickers."
            ),
        )
    from investorai_mcp.tools.get_price_history import get_price_history
    result = await get_price_history(symbol, range=range, price_type=price_type)
    return result

@router.get("/stocks/{symbol}/summary")
@limiter.limit("120/minute")
async def get_summary(
    request: Request, 
    symbol: str, 
    range: Literal["1W","1M","3M","6M","1Y","3Y","5Y"] = "1Y",
):
    symbol = symbol.upper()
    if not is_supported(symbol):
        return JSONResponse(
            status_code=404,
            content = make_error(
                "TICKER_NOT_SUPPORTED",
                f"Ticker '{symbol}' is not in supported universe.",
                "Use /tickers/search to find supported tickers."
            ),
        )
    from investorai_mcp.tools.get_daily_summary import get_daily_summary
    result = await get_daily_summary(symbol, range=range)
    return result

@router.get("/stocks/{symbol}/news")
@limiter.limit("120/minute")
async def get_news_endpoint(
    request: Request, 
    symbol: str, 
    limit: int = Query(10, ge=1, le=50),
):
    symbol = symbol.upper()
    if not is_supported(symbol):
        return JSONResponse(
            status_code=404,
            content = make_error(
                "TICKER_NOT_SUPPORTED",
                f"Ticker '{symbol}' is not in supported universe.",
                "Use /tickers/search to find supported tickers."
            ),
        )
    from investorai_mcp.tools.get_news import get_news
    result = await get_news(symbol, limit=limit)
    return result

@router.get("/stocks/{symbol}/sentiment")
@limiter.limit("120/minute")
async def get_sentiment_endpoint(
    request: Request, 
    symbol: str, 
):
    symbol = symbol.upper()
    if not is_supported(symbol):
        return JSONResponse(
            status_code=404,
            content = make_error(
                "TICKER_NOT_SUPPORTED",
                f"Ticker '{symbol}' is not in supported universe.",
                "Use /tickers/search to find supported tickers."
            ),
        )
    from investorai_mcp.tools.get_sentiment import get_sentiment
    result = await get_sentiment(symbol)
    return result

@router.get("/stocks/{symbol}/cache")
async def get_cache_endpoint(
    request: Request,
    symbol: str,
):
    symbol = symbol.upper()
    if not is_supported(symbol):
        return JSONResponse(
            status_code=404,
            content = make_error(
                "TICKER_NOT_SUPPORTED",
                f"Ticker '{symbol}' is not in supported universe.",
                "Use /tickers/search to find supported tickers."
            ),
        )
    from investorai_mcp.tools.get_cache_status import get_cache_status
    result = await get_cache_status(symbol)
    return result

@router.post("/stocks/{symbol}/refresh")
@limiter.limit("1/5minute")
async def refresh_cache_endpoint(
    request: Request,
    symbol: str,
):
    symbol = symbol.upper()
    if not is_supported(symbol):
        return JSONResponse(
            status_code=404,
            content = make_error(
                "TICKER_NOT_SUPPORTED",
                f"Ticker '{symbol}' is not in supported universe.",
                "Use /tickers/search to find supported tickers."
            ),
        )
    from investorai_mcp.tools.refresh_ticker import refresh_ticker
    result = await refresh_ticker(symbol)
    return result

#### AI Endpoints ---------------------------------------

@router.post("/stocks/{symbol}/trend")
@limiter.limit("10/minute")
async def get_trend_endpoint(
    request: Request,
    symbol: str,
):
    symbol = symbol.upper()
    if not is_supported(symbol):
        return JSONResponse(
            status_code=404,
            content = make_error(
                "TICKER_NOT_SUPPORTED",
                f"Ticker '{symbol}' is not in supported universe.",
                "Use /tickers/search to find supported tickers."
            ),
        )
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    body = await request.json()
    result = await get_trend_summary(symbol, 
                    range=body.get("range", "1Y"),
                    question = body.get("question", "Summarise this stock's recent performance."),
    )
    return result

@router.post("/chat")
@limiter.limit("20/minute")
async def chat_endpoint(request: Request):
    body = await request.json()
    symbol = body.get("ticker", "AAPL").upper()
    question = body.get("question", "")
    history = body.get("history", [])
    range_ = body.get("range", "1Y")
    
    if not question:
        return JSONResponse(
            status_code=400,
            content = make_error(
                "MISSING_QUESTION",
                "The 'question' field is required in the request body.",
                "Provide a question to ask about the stock."
            ),
        )
        
    from investorai_mcp.tools.get_trend_summary import get_trend_summary
    result = await get_trend_summary(
        symbol,
        range=range_,
        question=question,
        history=history if history else None,
    )
    return result

### ---LLM Validation -------------------------------

@router.post("/llm/validate")
@limiter.limit("5/minute")
async def validate_llm_key(request: Request):
    body = await request.json()
    api_key = body.get("api_key")
    model = body.get("model", "claude-sonnet-4-20250514")
    if not api_key:
        return JSONResponse(
            status_code=400,
            content = make_error(
                "MISSING_KEY",
                "api_key is required."),
        )
        
    try:
        import litellm
        response = await litellm.acompletion(
            model = model,
            messages = [{"role": "user", "content": "Hello, world!"}],
            api_key = api_key,
            max_tokens = 5,
        )
        return {"valid": True, "model": model}
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content = make_error(
                "LLM_KEY_INVALID",
                f"API key validation failed: {str(e)}",
            ),
        )
        
@router.post("/chat/stream")
@limiter.limit("20/minute")
async def chat_stream(request: Request):
    import json
    import asyncio
    from fastapi.responses import StreamingResponse

    # Read API key from header — never stored, used per-request only
    api_key = request.headers.get("X-LLM-API-Key")

    body     = await request.json()
    symbol   = body.get("symbol", "AAPL").upper()
    question = body.get("question", "")
    history  = body.get("history", [])
    range_   = body.get("range", "1Y")

    if not question:
        return JSONResponse(
            status_code=400,
            content=make_error("MISSING_QUESTION", "question field is required."),
        )

    if not is_supported(symbol):
        return JSONResponse(
            status_code=404,
            content=make_error("TICKER_NOT_SUPPORTED",
                               f"{symbol} is not in the supported universe."),
        )

    async def event_stream():
        _start_ns  = _time.time_ns()
        _total_ms  = 0
        _req_status = "success"

        try:
            yield f"data: {json.dumps({'type': 'start', 'symbol': symbol})}\n\n"

            # Override settings key with user-provided key if present
            if api_key:
                import os
                os.environ["LLM_API_KEY"] = api_key
                from investorai_mcp.config import settings
                settings.llm_api_key = api_key

            from investorai_mcp.tools.get_trend_summary import get_trend_summary
            result = await get_trend_summary(
                symbol,
                range="5Y",   # chat always gets max data; question range detection narrows it
                question=question,
                history=history if history else None,
            )

            # Capture server-side processing time (before streaming)
            _total_ms = (_time.time_ns() - _start_ns) // 1_000_000

            if "error" in result and result["error"]:
                _req_status = "error"
                yield f"data: {json.dumps({'type': 'error', 'message': result['message']})}\n\n"
                return

            summary = result.get("summary", "")
            words   = summary.split(" ")

            for i, word in enumerate(words):
                chunk = word + (" " if i < len(words) - 1 else "")
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
                await asyncio.sleep(0.03)

            yield f"data: {json.dumps({'type': 'citations', 'citations': result.get('citations', [])})}\n\n"
            yield f"data: {json.dumps({'type': 'stats',     'stats':     result.get('stats', {})})}\n\n"
            yield f"data: {json.dumps({'type': 'done',      'validation_passed': result.get('validation_passed', False)})}\n\n"

        except Exception as e:
            _req_status = "error"
            _total_ms = (_time.time_ns() - _start_ns) // 1_000_000
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        finally:
            if _total_ms > 0:
                try:
                    await _log_chat_request(
                        question=question,
                        symbols=symbol,
                        range_=range_,
                        total_latency_ms=_total_ms,
                        status=_req_status,
                    )
                except Exception:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        },
    )
    
# ── Monitoring ────────────────────────────────────────────────────────────

@router.get("/monitoring/db")
async def monitoring_db(request: Request):
    """Data health stats from local SQLite DB."""
    from sqlalchemy import func, select, text
    from investorai_mcp.db import AsyncSessionLocal
    from investorai_mcp.db.models import (
        CacheMetadata, LLMUsageLog, PriceHistory, EvalLog
    )
    from investorai_mcp.stocks import SUPPORTED_TICKERS

    async with AsyncSessionLocal() as session:

        # Total price rows
        total_rows = (await session.execute(
            select(func.count()).select_from(PriceHistory)
        )).scalar()

        # Rows per ticker
        rows_per_ticker = (await session.execute(
            select(PriceHistory.symbol, func.count().label("count"))
            .group_by(PriceHistory.symbol)
            .order_by(func.count().desc())
        )).all()

        # Stale tickers
        stale_count = (await session.execute(
            select(func.count()).select_from(CacheMetadata)
            .where(CacheMetadata.is_stale == True)
        )).scalar()

        # LLM usage today
        from datetime import datetime, timezone, timedelta
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        llm_today = (await session.execute(
            select(
                func.count().label("total"),
                func.avg(LLMUsageLog.latency_ms).label("avg_latency"),
                func.sum(LLMUsageLog.tokens_in).label("total_tokens_in"),
                func.sum(LLMUsageLog.tokens_out).label("total_tokens_out"),
                func.avg(LLMUsageLog.tokens_in).label("avg_tokens_in"),
                func.avg(LLMUsageLog.tokens_out).label("avg_tokens_out"),
            )
            .where(LLMUsageLog.ts >= today_start)
        )).one()

        # LLM usage last 7 days
        week_start = datetime.now(timezone.utc) - timedelta(days=7)
        llm_week = (await session.execute(
            select(
                func.count().label("total"),
                func.avg(LLMUsageLog.latency_ms).label("avg_latency"),
                func.sum(LLMUsageLog.tokens_in).label("total_tokens_in"),
                func.sum(LLMUsageLog.tokens_out).label("total_tokens_out"),
            )
            .where(LLMUsageLog.ts >= week_start)
        )).one()

        # Pass rate from eval log
        eval_total = (await session.execute(
            select(func.count()).select_from(EvalLog)
            .where(EvalLog.ts >= week_start)
        )).scalar() or 0

        eval_passed = (await session.execute(
            select(func.count()).select_from(EvalLog)
            .where(EvalLog.ts >= week_start)
            .where(EvalLog.pass_fail == "PASS")
        )).scalar() or 0

        # Provider breakdown
        provider_breakdown = (await session.execute(
            select(
                LLMUsageLog.provider,
                func.count().label("count"),
            )
            .where(LLMUsageLog.ts >= week_start)
            .group_by(LLMUsageLog.provider)
        )).all()

        # Error breakdown
        error_breakdown = (await session.execute(
            select(
                LLMUsageLog.status,
                func.count().label("count"),
            )
            .where(LLMUsageLog.ts >= week_start)
            .group_by(LLMUsageLog.status)
        )).all()

        # Daily query counts for sparkline (last 7 days)
        daily_counts = (await session.execute(
            select(
                func.date(LLMUsageLog.ts).label("day"),
                func.count().label("count"),
            )
            .where(LLMUsageLog.ts >= week_start)
            .group_by(func.date(LLMUsageLog.ts))
            .order_by(func.date(LLMUsageLog.ts))
        )).all()

    return {
        "price_data": {
            "total_rows":      total_rows,
            "tickers_covered": len(rows_per_ticker),
            "stale_count":     stale_count,
            "rows_per_ticker": [
                {"symbol": r.symbol, "count": r.count}
                for r in rows_per_ticker[:10]
            ],
        },
        "llm_today": {
            "total_queries":  llm_today.total     or 0,
            "avg_latency_ms": round(llm_today.avg_latency or 0),
            "tokens_in":      llm_today.total_tokens_in  or 0,
            "tokens_out":     llm_today.total_tokens_out or 0,
            "avg_tokens_in":  round(llm_today.avg_tokens_in  or 0),
            "avg_tokens_out": round(llm_today.avg_tokens_out or 0),
        },
        "llm_week": {
            "total_queries":  llm_week.total     or 0,
            "avg_latency_ms": round(llm_week.avg_latency or 0),
            "tokens_in":      llm_week.total_tokens_in  or 0,
            "tokens_out":     llm_week.total_tokens_out or 0,
        },
        "quality": {
            "eval_total":  eval_total,
            "eval_passed": eval_passed,
            "pass_rate":   round(eval_passed / eval_total * 100, 1)
                           if eval_total > 0 else None,
        },
        "providers": [
            {"provider": r.provider, "count": r.count}
            for r in provider_breakdown
        ],
        "errors": [
            {"status": r.status, "count": r.count}
            for r in error_breakdown
        ],
        "daily_counts": [
            {"day": str(r.day), "count": r.count}
            for r in daily_counts
        ],
    }


@router.get("/monitoring/langfuse")
async def monitoring_langfuse(request: Request):
    """Fetch recent traces from Langfuse API."""
    from investorai_mcp.config import settings
    import httpx

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return JSONResponse(
            status_code=503,
            content=make_error(
                "LANGFUSE_NOT_CONFIGURED",
                "Langfuse keys not set in environment.",
                "Add LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to .env",
            ),
        )

    host = settings.langfuse_host.rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Fetch recent traces
            traces_resp = await client.get(
                f"{host}/api/public/traces",
                params={"limit": 50, "orderBy": "timestamp.desc"},
                auth=(settings.langfuse_public_key,
                      settings.langfuse_secret_key),
            )
            traces_resp.raise_for_status()
            traces_data = traces_resp.json()

            # Fetch usage stats
            usage_resp = await client.get(
                f"{host}/api/public/metrics/usage",
                auth=(settings.langfuse_public_key,
                      settings.langfuse_secret_key),
            )
            usage_data = usage_resp.json() if usage_resp.status_code == 200 else {}

    except httpx.HTTPStatusError as e:
        return JSONResponse(
            status_code=502,
            content=make_error(
                "LANGFUSE_API_ERROR",
                f"Langfuse API returned {e.response.status_code}",
                str(e),
            ),
        )
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content=make_error("LANGFUSE_UNREACHABLE", str(e)),
        )

    traces = traces_data.get("data", [])

    # Compute summary from traces
    latencies  = [t.get("latency", 0) for t in traces if t.get("latency")]
    avg_latency = round(sum(latencies) / len(latencies)) if latencies else 0

    return {
        "traces":      traces[:20],
        "total_traces": traces_data.get("meta", {}).get("totalItems", len(traces)),
        "avg_latency_ms": avg_latency,
        "usage":       usage_data,
    }


@router.get("/monitoring/latency")
async def monitoring_latency(request: Request):
    """
    End-to-end chat latency statistics with P50/P95/P99 and outlier list.

    Outliers = calls whose server-side processing time exceeded the P95
    threshold computed from all recorded calls.
    """
    from sqlalchemy import select
    from investorai_mcp.db import AsyncSessionLocal
    from investorai_mcp.db.models import ChatRequestLog

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(ChatRequestLog)
            .order_by(ChatRequestLog.ts.asc())
        )).scalars().all()

    total = len(rows)
    if total == 0:
        return {
            "total_calls": 0,
            "p50_ms": None, "p95_ms": None, "p99_ms": None,
            "avg_ms": None,
            "outliers": [],
        }

    success_rows = [r for r in rows if r.status == "success"]
    latencies    = sorted(r.total_latency_ms for r in success_rows)

    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    p99 = _percentile(latencies, 99)
    avg = round(sum(latencies) / len(latencies)) if latencies else 0

    outliers = sorted(
        [
            {
                "id":               r.id,
                "ts":               r.ts.isoformat(),
                "question":         r.question,
                "symbols":          r.symbols,
                "range":            r.range,
                "total_latency_ms": r.total_latency_ms,
                "excess_ms":        r.total_latency_ms - p95,
            }
            for r in success_rows
            if r.total_latency_ms > p95
        ],
        key=lambda x: x["total_latency_ms"],
        reverse=True,
    )

    return {
        "total_calls":    total,
        "success_calls":  len(success_rows),
        "p50_ms":         p50,
        "p95_ms":         p95,
        "p99_ms":         p99,
        "avg_ms":         avg,
        "outlier_count":  len(outliers),
        "outliers":       outliers[:50],
    }