"""
Get trend summary MCP tool

Generates AN AI nattiative summary of a stock's price trend. 
Uses the full AI pipeline :
    Prompt Builder -> LiteLLM -> Post-gen validator -> Citation Extractor -> Langfuse
"""

import hashlib
from datetime import datetime, timezone
from typing import Literal

from fastmcp import Context

from investorai_mcp.data.yfinance_adapter import YFinanceAdapter
from investorai_mcp.db import AsyncSessionLocal
from investorai_mcp.db.cache_manager import CacheManager
from investorai_mcp.llm.citations import extract_citations, verify_citations_present
from investorai_mcp.llm.history import compress_history
from investorai_mcp.llm.litellm_client import call_llm
from investorai_mcp.llm.prompt_builder import build_prompt, compute_stats
from investorai_mcp.llm.validator import IDK_RESPONSE, validate_response
from investorai_mcp.server import mcp
from investorai_mcp.stocks import is_supported

_adapter = YFinanceAdapter()

@mcp.tool()
async def get_trend_summary(
    ticker_symbol:str, 
    range: Literal["1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"] = "1Y",
    question: str = "Summarise this stock's recent performance.",
    history: list[dict] | None = None,
    ctx: Context | None = None,
) -> dict:
    """
    Generate an AI narrative summary of a stock's price trend. 
    
    Uses only data from the local database - never training knowldege
    Every number in the response is verified against DB. 
    Citations are included for every financial figure. 
    
    Use this tool when user asks:
     - "How has AAPL performed over the last year?"
     - "Give me the summary of TSLA's recent trend"
     - "What happened to NVDA in the last 6 months?"
    
    Do not call for tickers outside the 50-stock universe.
    Requires a valid LLM_API_KEY in the environment settings
    
    Args:
        ticker_symbol: Uppercase ticker e.g: AAPL, TSLA, NVDA
        range: 1W, 1M, 3M, 6M, 1Y, 3Y, 5Y, Default is 1Y
        question: Specific question to answer. Default is general summary. 
        history: Optional compressed chat history for the context. 

    Returns:
        Dict with AI summary, citations, validation status, token usage. 
    """
    symbol = ticker_symbol.strip().upper()
    
    if not is_supported(symbol):
        return {
            "error": True, 
            "code": "TICKER_NOT_SUPPORTED",
            "message": f"{symbol} is not in the supported universe of 50 stocks.",
            "hint": "Use search_ticker tool to find supported tickers."
        }
    
    #generate anonymous session hash for usage tracking
    session_hash = hashlib.sha256(
        f"{symbol}{datetime.now(timezone.utc).date()}".encode()
    ).hexdigest()[:16]
    
    
    # fetch price data from cache
    async with AsyncSessionLocal() as session:
        manager = CacheManager(session, _adapter)
        await manager.ensure_ticker_exists(symbol)
        cache_result = await manager.get_prices(symbol, range)
        
    
    if not cache_result.data:
        return{
            "error": True,
            "code": "NO_UNAVILABLE",
            "message": f"No price data available for {symbol}"
        }
        
    #compute stats - never pass raw rows to LLM
    stats = compute_stats(symbol, range, cache_result.data)
    if stats is None:
        return{
            "error": True, 
            "code": "DATA_UNAVILABLE",
            "message": f"Could not compute statistics for {symbol}"
        }
        
    #compress chat history if provided
    compressed_history = None
    if history:
        compressed_history = await compress_history(
            history, session_hash=session_hash
        )
    
    # Build the LLM prompt
    messages = build_prompt(
        stats = stats, 
        question = question,
        history = compressed_history
    )
    
    # Call the LLm
    try:
        raw_response = await call_llm(
            messages = messages, 
            session_hash = session_hash, 
            tool_name = "get_trend_summary"
        )
    except RuntimeError as e:
        return {
            "error": True, 
            "code": "LLM_UNAVILABLE", 
            "message": str(e)
        }
        
    #validate - check all numbers against DB
    validation = validate_response(raw_response, stats)
    
    #extract citaitons
    citation_result = extract_citations(validation.response)
    
    return {
        "symbol" : symbol,
        "range": range,
        "summary": citation_result.clean_text, 
        "citations": [
            {"type": c.citation_type, "date": c.date}
            for c in citation_result.db_citations
        ] + [
            {"type": c.citation_type, "publisher": c.publisher, "url": c.url}
            for c in citation_result.news_citations
        ],
        "validation_passed": validation.passed,
        "is_stale": cache_result.is_stale,
        "data_age_hours": round(cache_result.data_age_hours, 2),
        "stats": {
            "start_price": stats.start_price,
            "end_price": stats.end_price,
            "period_return_pct": stats.period_return_pct,
            "high_price": stats.high_price,
            "low_price": stats.low_price,
            "volatality_pct": stats.volatality_pct,
            "trading_days": stats.trading_days,
        
        },

    }
        
