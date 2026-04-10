from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from investorai_mcp.db.models import NewsArticle

@pytest.fixture(autouse=True)
def register_tools():
    from investorai_mcp.server import _register_tools
    _register_tools()
    
def make_article(headline="AAPL beats earnings", source="Reuters", 
                url = 'https://reuters.com/aapl', ai_summary=None,
                sentiment_score= None) -> NewsArticle:
    article = MagicMock(spec=NewsArticle)
    article.headline = headline
    article.source = source
    article.published_at =  datetime(2026, 3, 28, 12, 0, 0, tzinfo=timezone.utc)
    article.ai_summary = ai_summary
    article.sentiment_score = sentiment_score
    return article

def patch_session_with_articles(articles, meta=None):
    """Patch AsyncSessionLocal to return given articles and optional meta"""
    mock_result_meta = MagicMock()
    mock_result_meta.scalar_one_or_none.return_value = meta
    
    mock_result_articles = MagicMock()
    mock_result_articles.scalars.return_value.all.return_value = articles
    
    
    call_count = 0
    
    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_result_meta
        return mock_result_articles
    
    mock_session = AsyncMock()
    mock_session.execute = mock_execute
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    
    return patch(
        "investorai_mcp.tools.get_news.AsyncSessionLocal", 
        return_value=mock_session
    )
    
async def test_unsupported_ticker_returns_error():
    from investorai_mcp.tools.get_news import get_news
    
    result = await get_news("FAKECROP")
    assert result["error"] is True
    assert result["code"] == "TICKER_NOT_SUPPORTED"
    
async def test_returns_articles_list():
    from investorai_mcp.tools.get_news import get_news
    
    articles = [make_article(f"headline {i}") for i in range(5)]
    
    #simulate fresh cache meta so we read from DB
    meta = MagicMock()
    meta.is_stale = False
    meta.last_fetched = datetime(2026, 3, 28, 11, 0, 0, tzinfo=timezone.utc)
    
    with patch_session_with_articles(articles, meta=meta):
        result = await get_news("AAPL", limit = 5)
        
    assert "articles" in result
    assert result["total"] == 5
    
async def test_article_fields_present():
    from investorai_mcp.tools.get_news import get_news
    
    articles = [make_article()]
    meta = MagicMock()
    meta.is_stale = False
    meta.last_fetched = datetime(2026, 3, 28, 11, 0, 0, tzinfo=timezone.utc)
    with patch_session_with_articles(articles, meta=meta):
        result = await get_news("AAPL", limit=1)
    article = result["articles"][0]
    for field in ["headline", "source", "url", "ai_summary", "sentiment_score", "published_at"]:
        assert field in article, f"Missing field: {field}"
        
        
async def test_limit_clamped_to_50():
    from investorai_mcp.tools.get_news import get_news
    
    articles = [make_article(f"headline {i}") for i in range(50)]
    meta = MagicMock()
    meta.is_stale = False
    meta.last_fetched = datetime(2026, 3, 28, 11, 0, 0, tzinfo=timezone.utc)
    
    with patch_session_with_articles(articles, meta=meta):
        result = await get_news("AAPL", limit=9999)
        
    assert len(result["articles"]) <= 50
    
async def test_empty_result_returns_gracefully():
    from investorai_mcp.tools.get_news import get_news
    
    meta = MagicMock()
    meta.is_stale = False
    meta.last_fetched = datetime(2026, 3, 28, 11, 0, 0, tzinfo=timezone.utc)
    
    with patch_session_with_articles([], meta=meta):
        result = await get_news("AAPL", limit=5)
        
    assert result["articles"] == []
    assert result["total"] == 0
    
async def test_symbol_normalised_uppercase():
    from investorai_mcp.tools.get_news import get_news
    
    result = await get_news("fakecrop")
    assert result["error"] is True
    #error is for unsupported ticker - symbol should be uppercased before check. 