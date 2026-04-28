"""
FastAPI BFF - Backend and frontend

REST layer consumed by React Web UI.
No business logic here - calls the same internal services
as the MCP tools

"""

import asyncio
import logging
import math
import time as _time
from datetime import UTC, datetime, timedelta
from typing import Literal

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Query, Request
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
    ttft_ms: int | None = None,
    db_fetch_ms: int | None = None,
    llm_ms: int | None = None,
    validation_ms: int | None = None,
) -> None:
    """Persist one chat call row to chat_request_log."""
    from investorai_mcp.db import AsyncSessionLocal
    from investorai_mcp.db.models import ChatRequestLog

    async with AsyncSessionLocal() as session:
        try:
            session.add(
                ChatRequestLog(
                    question=question,
                    symbols=symbols,
                    range=range_,
                    total_latency_ms=total_latency_ms,
                    ttft_ms=ttft_ms,
                    db_fetch_ms=db_fetch_ms,
                    llm_ms=llm_ms,
                    validation_ms=validation_ms,
                    status=status,
                    ts=datetime.now(UTC),
                )
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _percentile(sorted_values: list[int], p: float) -> int:
    """Return the p-th percentile from a pre-sorted list."""
    if not sorted_values:
        return 0
    idx = math.ceil(len(sorted_values) * p / 100) - 1
    return sorted_values[max(0, min(idx, len(sorted_values) - 1))]


# ---- Health ------------------------------------------


@router.get("/health")
async def health():
    from sqlalchemy import text

    from investorai_mcp.config import settings
    from investorai_mcp.db import AsyncSessionLocal

    checks: dict[str, dict] = {}

    # DB ping — SELECT 1
    try:
        t0 = _time.monotonic()
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["db"] = {
            "status": "ok",
            "latency_ms": round((_time.monotonic() - t0) * 1000),
        }
    except Exception as e:
        logger.error("Health check DB ping failed: %s", e)
        checks["db"] = {"status": "error", "detail": "database unreachable"}

    # LLM config — no live call, just confirm key is present
    if settings.llm_api_key:
        checks["llm"] = {"status": "ok", "provider": settings.llm_provider}
    else:
        checks["llm"] = {"status": "not_configured"}

    overall = "ok" if checks["db"]["status"] == "ok" else "degraded"
    status_code = 200 if overall == "ok" else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall,
            "version": "0.1.0",
            "checks": checks,
            "transport": settings.mcp_transport,
            "ai_enabled": settings.ai_chat_enabled,
            "provider": settings.data_provider,
        },
    )


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
    range: Literal["1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"] = "1Y",
    price_type: Literal["adj_close", "avg_price", "close"] = "adj_close",
):
    symbol = symbol.upper()
    if not is_supported(symbol):
        return JSONResponse(
            status_code=404,
            content=make_error(
                "TICKER_NOT_SUPPORTED",
                f"Ticker '{symbol}' is not in supported universe.",
                "Use /tickers/search to find supported tickers.",
            ),
        )
    from investorai_mcp.tools.get_price_history import get_price_history

    result = await get_price_history(symbol, range=range, price_type=price_type)
    if isinstance(result, dict) and result.get("error"):
        return JSONResponse(status_code=503, content=result)
    return result


@router.get("/stocks/{symbol}/summary")
@limiter.limit("120/minute")
async def get_summary(
    request: Request,
    symbol: str,
    range: Literal["1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"] = "1Y",
):
    symbol = symbol.upper()
    if not is_supported(symbol):
        return JSONResponse(
            status_code=404,
            content=make_error(
                "TICKER_NOT_SUPPORTED",
                f"Ticker '{symbol}' is not in supported universe.",
                "Use /tickers/search to find supported tickers.",
            ),
        )
    from investorai_mcp.tools.get_daily_summary import get_daily_summary

    result = await get_daily_summary(symbol, range=range)
    if isinstance(result, dict) and result.get("error"):
        return JSONResponse(status_code=503, content=result)
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
            content=make_error(
                "TICKER_NOT_SUPPORTED",
                f"Ticker '{symbol}' is not in supported universe.",
                "Use /tickers/search to find supported tickers.",
            ),
        )
    from investorai_mcp.tools.get_news import get_news

    result = await get_news(symbol, limit=limit)
    if isinstance(result, dict) and result.get("error"):
        return JSONResponse(status_code=503, content=result)
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
            content=make_error(
                "TICKER_NOT_SUPPORTED",
                f"Ticker '{symbol}' is not in supported universe.",
                "Use /tickers/search to find supported tickers.",
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
            content=make_error(
                "TICKER_NOT_SUPPORTED",
                f"Ticker '{symbol}' is not in supported universe.",
                "Use /tickers/search to find supported tickers.",
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
            content=make_error(
                "TICKER_NOT_SUPPORTED",
                f"Ticker '{symbol}' is not in supported universe.",
                "Use /tickers/search to find supported tickers.",
            ),
        )
    from investorai_mcp.tools.refresh_ticker import refresh_ticker

    result = await refresh_ticker(symbol)
    return result


#### AI Endpoints ---------------------------------------


### ---LLM Validation -------------------------------


@router.post("/llm/validate")
@limiter.limit("3/minute")
async def validate_llm_key(request: Request):
    body = await request.json()
    api_key = body.get("api_key")
    model = body.get("model", "claude-sonnet-4-20250514")
    if not api_key:
        return JSONResponse(
            status_code=400,
            content=make_error("MISSING_KEY", "api_key is required."),
        )

    try:
        import litellm

        await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": "Hello, world!"}],
            api_key=api_key,
            max_tokens=5,
        )
        return {"valid": True, "model": model}
    except Exception:
        await asyncio.sleep(1)  # slow enumeration attempts
        return JSONResponse(
            status_code=400,
            content=make_error(
                "LLM_KEY_INVALID",
                "API key validation failed.",
            ),
        )


@router.post("/chat/stream")
@limiter.limit("20/minute")
async def chat_stream(request: Request):
    import json

    # Read API key from header — never stored, used per-request only
    api_key = request.headers.get("X-LLM-API-Key")

    body = await request.json()
    symbol = body.get("symbol", "AAPL").upper()
    question = body.get("question", "")
    history = body.get("history", [])
    range_ = body.get("range", "1Y")

    if not question:
        return JSONResponse(
            status_code=400,
            content=make_error("MISSING_QUESTION", "question field is required."),
        )

    from investorai_mcp.config import settings

    if not api_key and not settings.llm_api_key:
        return JSONResponse(
            status_code=400,
            content=make_error(
                "MISSING_API_KEY",
                "Provide an LLM API key via X-LLM-API-Key header or set LLM_API_KEY in server config.",
            ),
        )

    if not is_supported(symbol):
        return JSONResponse(
            status_code=404,
            content=make_error(
                "TICKER_NOT_SUPPORTED", f"{symbol} is not in the supported universe."
            ),
        )

    async def event_stream():
        _start_ns = _time.time_ns()
        _total_ms = 0
        _ttft_ms: int | None = None
        _db_fetch_ms: int | None = None
        _llm_ms: int | None = None
        _validation_ms: int | None = None
        _req_status = "success"

        try:
            yield f"data: {json.dumps({'type': 'start', 'symbol': symbol})}\n\n"

            import hashlib
            from investorai_mcp.llm.agent import run_agent_loop

            _key_token = (api_key or "anonymous")[:16]
            session_hash = hashlib.sha256(
                f"{_key_token}{symbol}{datetime.now(UTC).date()}".encode()
            ).hexdigest()[:16]

            _got_response = False
            try:
                async with asyncio.timeout(120):  # hard ceiling: 2 minutes
                    async for event in run_agent_loop(
                        question=question,
                        history=history if history else None,
                        api_key=api_key or None,
                        session_hash=session_hash,
                    ):
                        if event["type"] == "token":
                            if _ttft_ms is None:
                                _ttft_ms = (_time.time_ns() - _start_ns) // 1_000_000
                            _got_response = True
                        if event["type"] == "done":
                            _total_ms = (_time.time_ns() - _start_ns) // 1_000_000
                        yield f"data: {json.dumps(event)}\n\n"
            except TimeoutError:
                _req_status = "error"
                _total_ms = (_time.time_ns() - _start_ns) // 1_000_000
                logger.warning("Chat stream timed out after 120s for symbol=%s", symbol)
                yield f"data: {json.dumps({'type': 'error', 'message': 'Request timed out. Try a simpler question or fewer stocks.'})}\n\n"

            if not _got_response and _req_status == "success":
                _req_status = "error"
                yield f"data: {json.dumps({'type': 'error', 'message': 'No response generated.'})}\n\n"

        except Exception as e:
            _req_status = "error"
            _total_ms = (_time.time_ns() - _start_ns) // 1_000_000
            logger.exception("Chat stream error for symbol=%s: %s", symbol, e)
            yield f"data: {json.dumps({'type': 'error', 'message': 'An error occurred. Please try again.'})}\n\n"

        finally:
            if _total_ms > 0:
                try:
                    await _log_chat_request(
                        question=question,
                        symbols=symbol,
                        range_=range_,
                        total_latency_ms=_total_ms,
                        ttft_ms=_ttft_ms,
                        db_fetch_ms=_db_fetch_ms,
                        llm_ms=_llm_ms,
                        validation_ms=_validation_ms,
                        status=_req_status,
                    )
                except Exception as log_err:
                    logger.warning("Failed to log chat request: %s", log_err)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


# ── Monitoring ────────────────────────────────────────────────────────────


@router.get("/monitoring/db")
async def monitoring_db(request: Request):
    """Data health stats from local SQLite DB."""
    from sqlalchemy import func, select

    from investorai_mcp.db import AsyncSessionLocal
    from investorai_mcp.db.models import CacheMetadata, EvalLog, LLMUsageLog, PriceHistory

    async with AsyncSessionLocal() as session:
        # Total price rows
        total_rows = (
            await session.execute(select(func.count()).select_from(PriceHistory))
        ).scalar()

        # Rows per ticker
        rows_per_ticker = (
            await session.execute(
                select(PriceHistory.symbol, func.count().label("count"))
                .group_by(PriceHistory.symbol)
                .order_by(func.count().desc())
            )
        ).all()

        # Stale tickers
        stale_count = (
            await session.execute(
                select(func.count())
                .select_from(CacheMetadata)
                .where(CacheMetadata.is_stale.is_(True))
            )
        ).scalar()

        # LLM usage today
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        llm_today = (
            await session.execute(
                select(
                    func.count().label("total"),
                    func.avg(LLMUsageLog.latency_ms).label("avg_latency"),
                    func.sum(LLMUsageLog.tokens_in).label("total_tokens_in"),
                    func.sum(LLMUsageLog.tokens_out).label("total_tokens_out"),
                    func.avg(LLMUsageLog.tokens_in).label("avg_tokens_in"),
                    func.avg(LLMUsageLog.tokens_out).label("avg_tokens_out"),
                ).where(LLMUsageLog.ts >= today_start)
            )
        ).one()

        # LLM usage last 7 days
        week_start = datetime.now(UTC) - timedelta(days=7)
        llm_week = (
            await session.execute(
                select(
                    func.count().label("total"),
                    func.avg(LLMUsageLog.latency_ms).label("avg_latency"),
                    func.sum(LLMUsageLog.tokens_in).label("total_tokens_in"),
                    func.sum(LLMUsageLog.tokens_out).label("total_tokens_out"),
                ).where(LLMUsageLog.ts >= week_start)
            )
        ).one()

        # Pass rate from eval log
        eval_total = (
            await session.execute(
                select(func.count()).select_from(EvalLog).where(EvalLog.ts >= week_start)
            )
        ).scalar() or 0

        eval_passed = (
            await session.execute(
                select(func.count())
                .select_from(EvalLog)
                .where(EvalLog.ts >= week_start)
                .where(EvalLog.pass_fail == "PASS")  # noqa: S105
            )
        ).scalar() or 0

        # Provider breakdown
        provider_breakdown = (
            await session.execute(
                select(
                    LLMUsageLog.provider,
                    func.count().label("count"),
                )
                .where(LLMUsageLog.ts >= week_start)
                .group_by(LLMUsageLog.provider)
            )
        ).all()

        # Error breakdown
        error_breakdown = (
            await session.execute(
                select(
                    LLMUsageLog.status,
                    func.count().label("count"),
                )
                .where(LLMUsageLog.ts >= week_start)
                .group_by(LLMUsageLog.status)
            )
        ).all()

        # Daily query counts for sparkline (last 7 days)
        daily_counts = (
            await session.execute(
                select(
                    func.date(LLMUsageLog.ts).label("day"),
                    func.count().label("count"),
                )
                .where(LLMUsageLog.ts >= week_start)
                .group_by(func.date(LLMUsageLog.ts))
                .order_by(func.date(LLMUsageLog.ts))
            )
        ).all()

    return {
        "price_data": {
            "total_rows": total_rows,
            "tickers_covered": len(rows_per_ticker),
            "stale_count": stale_count,
            "rows_per_ticker": [
                {"symbol": r.symbol, "count": r.count} for r in rows_per_ticker[:10]
            ],
        },
        "llm_today": {
            "total_queries": llm_today.total or 0,
            "avg_latency_ms": round(llm_today.avg_latency or 0),
            "tokens_in": llm_today.total_tokens_in or 0,
            "tokens_out": llm_today.total_tokens_out or 0,
            "avg_tokens_in": round(llm_today.avg_tokens_in or 0),
            "avg_tokens_out": round(llm_today.avg_tokens_out or 0),
        },
        "llm_week": {
            "total_queries": llm_week.total or 0,
            "avg_latency_ms": round(llm_week.avg_latency or 0),
            "tokens_in": llm_week.total_tokens_in or 0,
            "tokens_out": llm_week.total_tokens_out or 0,
        },
        "quality": {
            "eval_total": eval_total,
            "eval_passed": eval_passed,
            "pass_rate": round(eval_passed / eval_total * 100, 1) if eval_total > 0 else None,
        },
        "providers": [{"provider": r.provider, "count": r.count} for r in provider_breakdown],
        "errors": [{"status": r.status, "count": r.count} for r in error_breakdown],
        "daily_counts": [{"day": str(r.day), "count": r.count} for r in daily_counts],
    }


@router.get("/monitoring/langfuse")
async def monitoring_langfuse(request: Request):
    """Fetch recent traces from Langfuse API."""
    import httpx

    from investorai_mcp.config import settings

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
    if not host.startswith("https://"):
        return JSONResponse(
            status_code=400,
            content=make_error(
                "INVALID_LANGFUSE_HOST",
                "LANGFUSE_HOST must be an HTTPS URL.",
            ),
        )

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Fetch recent traces
            traces_resp = await client.get(
                f"{host}/api/public/traces",
                params={"limit": 50, "orderBy": "timestamp.desc"},
                auth=(settings.langfuse_public_key, settings.langfuse_secret_key),
            )
            traces_resp.raise_for_status()
            traces_data = traces_resp.json()

            # Fetch usage stats
            usage_resp = await client.get(
                f"{host}/api/public/metrics/usage",
                auth=(settings.langfuse_public_key, settings.langfuse_secret_key),
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
    latencies = [t.get("latency", 0) for t in traces if t.get("latency")]
    avg_latency = round(sum(latencies) / len(latencies)) if latencies else 0

    return {
        "traces": traces[:20],
        "total_traces": traces_data.get("meta", {}).get("totalItems", len(traces)),
        "avg_latency_ms": avg_latency,
        "usage": usage_data,
        "trace_url_base": f"{host}/trace",
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
        rows = (
            (await session.execute(select(ChatRequestLog).order_by(ChatRequestLog.ts.asc())))
            .scalars()
            .all()
        )

    total = len(rows)
    if total == 0:
        return {
            "total_calls": 0,
            "p50_ms": None,
            "p95_ms": None,
            "p99_ms": None,
            "avg_ms": None,
            "outliers": [],
        }

    success_rows = [r for r in rows if r.status == "success"]
    latencies = sorted(r.total_latency_ms for r in success_rows)

    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    p99 = _percentile(latencies, 99)
    avg = round(sum(latencies) / len(latencies)) if latencies else 0

    # TTFT stats — only rows that have ttft_ms recorded
    ttft_rows = [r.ttft_ms for r in success_rows if r.ttft_ms is not None]
    ttft_sorted = sorted(ttft_rows)
    ttft_stats = {
        "p50_ms": _percentile(ttft_sorted, 50) if ttft_sorted else None,
        "p95_ms": _percentile(ttft_sorted, 95) if ttft_sorted else None,
        "p99_ms": _percentile(ttft_sorted, 99) if ttft_sorted else None,
        "avg_ms": round(sum(ttft_sorted) / len(ttft_sorted)) if ttft_sorted else None,
        "samples": len(ttft_sorted),
    }

    def _component_stats(values: list[int]) -> dict:
        s = sorted(values)
        return {
            "p50_ms": _percentile(s, 50) if s else None,
            "p95_ms": _percentile(s, 95) if s else None,
            "p99_ms": _percentile(s, 99) if s else None,
            "avg_ms": round(sum(s) / len(s)) if s else None,
            "samples": len(s),
        }

    component_stats = {
        "db_fetch": _component_stats(
            [r.db_fetch_ms for r in success_rows if r.db_fetch_ms is not None]
        ),
        "llm": _component_stats([r.llm_ms for r in success_rows if r.llm_ms is not None]),
        "validation": _component_stats(
            [r.validation_ms for r in success_rows if r.validation_ms is not None]
        ),
    }

    outliers = sorted(
        [
            {
                "id": r.id,
                "ts": r.ts.isoformat(),
                "question": r.question,
                "symbols": r.symbols,
                "range": r.range,
                "total_latency_ms": r.total_latency_ms,
                "ttft_ms": r.ttft_ms,
                "excess_ms": r.total_latency_ms - p95,
            }
            for r in success_rows
            if r.total_latency_ms > p95
        ],
        key=lambda x: x["total_latency_ms"],
        reverse=True,
    )

    return {
        "total_calls": total,
        "success_calls": len(success_rows),
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
        "avg_ms": avg,
        "outlier_count": len(outliers),
        "outliers": outliers[:50],
        "ttft": ttft_stats,
        "components": component_stats,
    }
