"""
FastAPI BFF - Backend and frontend

Rest layer consumeed by React Web UI. 
No business logic here - calls the same internal services
as the MCP tools

"""

import uuid
from typing import Literal
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from investorai_mcp.api.error_handler import make_error
from investorai_mcp.api.rate_limit import limiter
from investorai_mcp.stocks import SUPPORTED_TICKERS, is_supported

router = APIRouter()

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
                range=range_,
                question=question,
                history=history if history else None,
            )

            if "error" in result and result["error"]:
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
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        },
    )