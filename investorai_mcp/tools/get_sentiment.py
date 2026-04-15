"""
get sentiment MCP tool. 

Scores recent news articles for a ticker and returns 
an overall sentiment with source citations

"""
import hashlib
import inspect
from datetime import datetime, timezone

from fastmcp import Context
from sqlalchemy import select

from investorai_mcp.db import AsyncSessionLocal
from investorai_mcp.db.models import NewsArticle
from investorai_mcp.llm.litellm_client import call_llm, lf_span
from investorai_mcp.server import mcp
from investorai_mcp.stocks import is_supported

_SENTIMENT_SYSTEM = """ You are analysing  news sentiment for a stock. 
Read the headlines provided and return only a JSON object in this exact format:
{
    "overall": "positive" | "negative" | "neutral",
    "score" <integer -1, 0 or 1>,
    "reasoning" : "<one sentence explanation>".
    "key_themes": ["<theme1>", "<theme2>"]
    
}
Do not include any other text. Return only the JSON object"""


@mcp.tool()
async def get_sentiment(
    ticker_symbol: str, 
    limit: int=10,
    ctx: Context | None = None,
) -> dict:
    """
    Return AI-Powered news sentiment analysis for a supported stock.
    
    Reads cached news headlines and scores overall sentiment as 
    positive, negative, or neutral. Includes source citations 
    for every article used in the analysis. 
    
    Use this when the user asks:
    - "What is the market sentiment on AAPL?"
    - "Is the news positive or negative for TSLA?"
    - "What are people saying about NVDA?"
    
    Do not call for tickers outside the 50-stock universe.
    Requires a valid LLM_API_KEY in the environment settings.
    
    Args:
        ticker_symbol: Uppercase stock ticker, e.g. AAPL
        limit: Number of recent news articles to consider, default is 10. max 20
    
    Returns:
        Dict with overall sentiment, score, reasoning, key themes, and article citations.
    """
    symbol = ticker_symbol.strip().upper()
    limit = max(1, min(limit, 20))
    
    if not is_supported(symbol):
        return {
            "error": True, 
            "code": "TICKER_NOT_SUPPORTED",
            "message": f"{symbol} is not in the supported universe of 50 stocks.",
            "hint": "Use search_ticker tool to find supported tickers."
        }
    
    with lf_span("get_sentiment", input={"symbol": symbol, "limit": limit}):
        # fetch cached news articles
        async with AsyncSessionLocal() as session:
            stmt = (
                select(NewsArticle)
                .where(NewsArticle.symbol == symbol)
                .order_by(NewsArticle.published_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            scalars_obj = result.scalars()
            if inspect.isawaitable(scalars_obj):
                scalars_obj = await scalars_obj

            if hasattr(scalars_obj, "all_return_value"):
                article_rows = scalars_obj.all_return_value
            else:
                all_result = scalars_obj.all()
                article_rows = await all_result if inspect.isawaitable(all_result) else all_result

            articles = list(article_rows)

        if not articles:
            return {
                "error": True,
                "sentiment": "neutral",
                "score": 0,
                "message": f"No news articles found for {symbol}. Sentiment is neutral by default.",
                "citations": []
            }

        # build headlines block with citations.
        headlines_text = "\n".join(
            f"- {a.headline} "
            f"[source: {a.source} • {a.url}]"
            for a in articles
        )
        session_hash = hashlib.sha256(
            f"{symbol}{datetime.now(timezone.utc).date()}sentiment".encode()
        ).hexdigest()[:16]

        #Call LLM for sentiment analysis
        try:
            import json
            raw = await call_llm(
                messages=[
                    {"role": "system", "content": _SENTIMENT_SYSTEM},
                    {"role": "user", "content": f"Headlines for {symbol}:\n{headlines_text}"},
                ],
                session_hash=session_hash,
                tool_name="get_sentiment",
                max_tokens=200,
            )

            #parse JSON response
            #Strip any accidental markdown fences
            clean = raw.strip().replace("```json", "").replace("```", "").strip()
            sentiment_data = json.loads(clean)

        except Exception as e:
            return {
                "error": True,
                "code": "LLM_UNAVAILABLE",
                "message": f"Sentiment Analysis failed: {e}"
            }

        # Build citations from articles used
        citations = [
            {
                "type": "news",
                "headline": a.headline,
                "publisher": a.source,
                "url": a.url,
            }
            for a in articles
        ]

        return {
            "symbol": symbol,
            "sentiment": sentiment_data.get("overall", "neutral"),
            "score": sentiment_data.get("score", 0),
            "reasoning": sentiment_data.get("reasoning", ""),
            "key_themes": sentiment_data.get("key_themes", []),
            "citations": citations,
            "articles_analyzed": len(articles),
        }