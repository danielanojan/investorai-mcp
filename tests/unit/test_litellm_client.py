""" Test for LiteLLM weapper. """
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.fixture
def mock_response():
    """ Fake LiteLLM response object"""
    response = MagicMock()
    response.choices[0].message.content = "AAPL closed at $174.32 [source: DB • 2026-03-28]"
    response.usage.prompt_tokens = 150
    response.usage.completion_tokens = 80
    return response

async def test_call_llm_returns_text(mock_response):
    from investorai_mcp.llm.litellm_client import call_llm
    
    with patch("investorai_mcp.llm.litellm_client.acompletion",
               new=AsyncMock(return_value=mock_response)), \
            patch("investorai_mcp.llm.litellm_client._log_usage",
                    new=AsyncMock()), \
            patch("investorai_mcp.llm.litellm_client.settings") as mock_settings:
            
        mock_settings.llm_api_key = "sk_test_key"
        mock_settings.llm_model = "claude-sonnet-4-20250514"     
        mock_settings.llm_provider = "anthropic"
        mock_settings.langfuse_public_key = None
        mock_settings.langfuse_secret_key = None
        
        result = await call_llm(
            messages = [{"role": "user", "content": "How is AAPL?"}],
            session_hash="test_session",
            tool_name="get_trend_summary",
        )
        
    assert isinstance(result, str)
    assert len(result) > 0
    
    
async def test_call_llm_raises_without_api_key():
    from investorai_mcp.llm.litellm_client import call_llm
    
    with patch("investorai_mcp.llm.litellm_client.settings") as mock_settings:
        mock_settings.llm_api_key = None
        
        with pytest.raises(RuntimeError, match="No LLM API key"):
            await call_llm(messages=[{"role": "user", "content": "test"}])
    
async def test_call_llm_logs_usage(mock_response):
    from investorai_mcp.llm.litellm_client import call_llm
    
    with patch("investorai_mcp.llm.litellm_client.acompletion",
               new=AsyncMock(return_value=mock_response)), \
            patch("investorai_mcp.llm.litellm_client._log_usage",
                    new=AsyncMock()) as mock_log, \
            patch("investorai_mcp.llm.litellm_client.settings") as mock_settings:
            
            
        mock_settings.llm_api_key = "sk_test_key"
        mock_settings.llm_model = "claude-sonnet-4-20250514"
        mock_settings.llm_provider = "anthropic"
        mock_settings.langfuse_public_key = None
        mock_settings.langfuse_secret_key = None
        
        await call_llm(
            messages = [{"role": "user", "content": "test"}],
            tool_name="get_trend_summary",
        )
        
    mock_log.assert_called_once()
    call_kwargs = mock_log.call_args.kwargs
    assert call_kwargs["tool_name"] == "get_trend_summary"
    assert call_kwargs["tokens_in"] == 150
    assert call_kwargs["tokens_out"] == 80
    assert call_kwargs["status"] == "success"
    
async def test_call_llm_logs_error_on_failure():
    from investorai_mcp.llm.litellm_client import call_llm
    
    with patch("investorai_mcp.llm.litellm_client.acompletion",
               new=AsyncMock(side_effect=Exception("LLM failure"))), \
            patch("investorai_mcp.llm.litellm_client._log_usage",
                    new=AsyncMock()) as mock_log, \
            patch("investorai_mcp.llm.litellm_client.settings") as mock_settings:
        
        mock_settings.llm_api_key = "sk_test_key"
        mock_settings.llm_model = "claude-sonnet-4-20250514"
        mock_settings.llm_provider = "anthropic"
        mock_settings.langfuse_public_key = None
        mock_settings.langfuse_secret_key = None
        
        with pytest.raises(RuntimeError): 
            await call_llm(messages=[{"role": "user", "content": "test"}])
    
    mock_log.assert_called_once()
    assert mock_log.call_args.kwargs["status"] == "error"
    
async def test_langfuse_skipped_when_not_configured():
    from investorai_mcp.llm.litellm_client import _get_langfuse_handler
    
    with patch("investorai_mcp.llm.litellm_client.settings") as mock_settings:
        mock_settings.langfuse_public_key = None
        mock_settings.langfuse_secret_key = None
        
        handler = _get_langfuse_handler()
        assert handler is None

async def test_call_llm_rate_limit_logged():
    import litellm as lt 
    from investorai_mcp.llm.litellm_client import call_llm
    
    with patch("investorai_mcp.llm.litellm_client.acompletion",
               new=AsyncMock(side_effect=lt.RateLimitError(
                   "rate limit", llm_provider="anthropic", model="claude"))), \
            patch("investorai_mcp.llm.litellm_client._log_usage",
                    new=AsyncMock()) as mock_log, \
            patch("investorai_mcp.llm.litellm_client.settings") as mock_settings:
                
        mock_settings.llm_api_key = "sk_test_key"
        mock_settings.llm_model = "claude-sonnet-4-20250514"
        mock_settings.llm_provider = "anthropic"
        mock_settings.langfuse_public_key = None
        mock_settings.langfuse_secret_key = None
        
        
        with pytest.raises(RuntimeError):
            await call_llm(messages=[{"role": "user", "content": "test"}])
            
    assert mock_log.call_args.kwargs["status"] == "rate_limited"
    
    
    