"""Test for the get_sentiment MCP tool"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import json

import pytest

from investorai_mcp.db.models import NewsArticle

@pytest.fixture(autouse=True)
def register_tools():
    from investorai_mcp.server import _register_tools
    _register_tools()
    
def make_article(headline="Apple beats earnings", source="Reuters", 
                 url="https://reuters.com/apple"):
    article = MagicMock(spec=NewsArticle)
    article.headline = headline
    article.source = source
    article.url = url
    article.published_at = datetime(2026, 3, 28, tzinfo=timezone.utc)
    return article

def patch_sentiment(articles, llm_response=None):
    if llm_response is None:
        llm_response = json.dumps({
            "overall": "positive",
            "score": 1, 
            "reasoning": "Strong earnings beat expectations.", 
            "key_themes": ["earnings", "growth"],
        })
        
    mock_result = AsyncMock()
    mock_result.scalars.return_value.all_return_value = articles
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    
    return (
        patch("investorai_mcp.tools.get_sentiment.AsyncSessionLocal", return_value=mock_session),
        patch("investorai_mcp.tools.get_sentiment.call_llm", return_value=llm_response),
    )
    
async def test_unsupported_ticker_returns_error():
    from investorai_mcp.tools.get_sentiment import get_sentiment
    
    result = await get_sentiment("FAKECROP")
    assert result["error"] is True
    assert result["code"] == "TICKER_NOT_SUPPORTED"
    
async def test_no_articles_return_neutral():
    from investorai_mcp.tools.get_sentiment import get_sentiment
    
    p1, p2 = patch_sentiment([])
    with p1, p2:
        result = await get_sentiment("AAPL")
    assert result["sentiment"] == "neutral"
    assert result["score"] == 0
    
async def test_positive_sentiment_returned():
    from investorai_mcp.tools.get_sentiment import get_sentiment
    
    articles = [make_article()]
    p1, p2 = patch_sentiment(articles)
    with p1, p2:
        result = await get_sentiment("AAPL")
    assert result["sentiment"] == "positive"
    assert result["score"] == 1
    
async def test_returns_reasoning():
    from investorai_mcp.tools.get_sentiment import get_sentiment
    
    articles = [make_article()]
    p1, p2 = patch_sentiment(articles)
    with p1, p2:
        result = await get_sentiment("AAPL")
    assert "reasoning" in result
    assert len(result["reasoning"]) > 0
    
async def test_returns_key_themes():
    from investorai_mcp.tools.get_sentiment import get_sentiment
    
    articles = [make_article()]
    p1, p2 = patch_sentiment(articles)
    with p1, p2:
        result = await get_sentiment("AAPL")
    assert "key_themes" in result
    assert isinstance(result["key_themes"], list)

async def test_returns_citations():
    from investorai_mcp.tools.get_sentiment import get_sentiment
    
    articles = [make_article()]
    p1, p2 = patch_sentiment(articles)
    with p1, p2:
        result = await get_sentiment("AAPL")
    assert "citations" in result
    assert len(result["citations"]) == 1
    assert result["citations"][0]["url"] == "https://reuters.com/apple"
    
async def test_articles_analysed_count():
    from investorai_mcp.tools.get_sentiment import get_sentiment
    
    articles = [make_article(f"Headline {i}") for i in range(5)]
    p1, p2 = patch_sentiment(articles)
    with p1, p2:
        result = await get_sentiment("AAPL")
    assert "articles_analyzed" in result
    assert result["articles_analyzed"] == 5
    
async def test_llm_failure_returns_error():
    from investorai_mcp.tools.get_sentiment import get_sentiment
    
    articles = [make_article()]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all_return_value = articles
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    with patch("investorai_mcp.tools.get_sentiment.AsyncSessionLocal",
               return_value=mock_session), \
         patch("investorai_mcp.tools.get_sentiment.call_llm",
               new=AsyncMock(side_effect=Exception("LLM down"))):
        result = await get_sentiment("AAPL")
    assert result["error"] is True
    assert result["code"]  == "LLM_UNAVAILABLE"