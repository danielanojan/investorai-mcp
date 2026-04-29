"""Test for LiteLLM wrapper."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_response():
    """Fake LiteLLM response object"""
    response = MagicMock()
    response.choices[0].message.content = "AAPL closed at $174.32 [source: DB • 2026-03-28]"
    response.usage.prompt_tokens = 150
    response.usage.completion_tokens = 80
    return response


async def test_call_llm_returns_text(mock_response):
    from investorai_mcp.llm.litellm_client import call_llm

    with (
        patch(
            "investorai_mcp.llm.litellm_client.acompletion",
            new=AsyncMock(return_value=mock_response),
        ),
        patch("investorai_mcp.llm.litellm_client._log_usage", new=AsyncMock()),
        patch("investorai_mcp.llm.litellm_client.settings") as mock_settings,
    ):
        mock_settings.llm_api_key = "sk_test_key"
        mock_settings.llm_model = "claude-sonnet-4-20250514"
        mock_settings.llm_provider = "anthropic"
        mock_settings.langfuse_public_key = None
        mock_settings.langfuse_secret_key = None

        result = await call_llm(
            messages=[{"role": "user", "content": "How is AAPL?"}],
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

    with (
        patch(
            "investorai_mcp.llm.litellm_client.acompletion",
            new=AsyncMock(return_value=mock_response),
        ),
        patch("investorai_mcp.llm.litellm_client._log_usage", new=AsyncMock()) as mock_log,
        patch("investorai_mcp.llm.litellm_client.settings") as mock_settings,
    ):
        mock_settings.llm_api_key = "sk_test_key"
        mock_settings.llm_model = "claude-sonnet-4-20250514"
        mock_settings.llm_provider = "anthropic"
        mock_settings.langfuse_public_key = None
        mock_settings.langfuse_secret_key = None

        await call_llm(
            messages=[{"role": "user", "content": "test"}],
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

    with (
        patch(
            "investorai_mcp.llm.litellm_client.acompletion",
            new=AsyncMock(side_effect=Exception("LLM failure")),
        ),
        patch("investorai_mcp.llm.litellm_client._log_usage", new=AsyncMock()) as mock_log,
        patch("investorai_mcp.llm.litellm_client.settings") as mock_settings,
    ):
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
        assert not handler


async def test_call_llm_rate_limit_logged():
    import litellm as lt

    from investorai_mcp.llm.litellm_client import call_llm

    with (
        patch(
            "investorai_mcp.llm.litellm_client.acompletion",
            new=AsyncMock(
                side_effect=lt.RateLimitError(
                    "rate limit", llm_provider="anthropic", model="claude"
                )
            ),
        ),
        patch("investorai_mcp.llm.litellm_client._log_usage", new=AsyncMock()) as mock_log,
        patch("investorai_mcp.llm.litellm_client.settings") as mock_settings,
    ):
        mock_settings.llm_api_key = "sk_test_key"
        mock_settings.llm_model = "claude-sonnet-4-20250514"
        mock_settings.llm_provider = "anthropic"
        mock_settings.langfuse_public_key = None
        mock_settings.langfuse_secret_key = None

        with pytest.raises(RuntimeError):
            await call_llm(messages=[{"role": "user", "content": "test"}])

    assert mock_log.call_args.kwargs["status"] == "rate_limited"


# ---------------------------------------------------------------------------
# _call_llm_streaming
# ---------------------------------------------------------------------------


def _make_stream_chunk(content=None, tool_call_delta=None):
    """Build a minimal streaming chunk object."""
    chunk = MagicMock()
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = [tool_call_delta] if tool_call_delta else None
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = delta
    return chunk


class _FakeStream:
    """Async-iterable that yields pre-built chunks, as litellm streaming responses do."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for chunk in self._chunks:
            yield chunk


def _make_full_response(content=""):
    resp = MagicMock()
    resp.choices[0].message.content = content
    resp.choices[0].message.tool_calls = None
    resp.usage.prompt_tokens = 100
    resp.usage.completion_tokens = 20
    return resp


async def _drain_streaming(gen):
    return [item async for item in gen]


async def test_streaming_yields_text_deltas():
    from investorai_mcp.llm.litellm_client import _call_llm_streaming

    chunks = [_make_stream_chunk("Hello"), _make_stream_chunk(" world")]
    full_resp = _make_full_response("Hello world")

    with (
        patch("investorai_mcp.llm.litellm_client.acompletion", new=AsyncMock(return_value=_FakeStream(chunks))),
        patch("investorai_mcp.llm.litellm_client.litellm") as mock_litellm,
        patch("investorai_mcp.llm.litellm_client._log_usage", new=AsyncMock()),
        patch("investorai_mcp.llm.litellm_client.settings") as mock_settings,
    ):
        mock_settings.llm_api_key = "sk-test"
        mock_settings.llm_model = "claude-sonnet-4-20250514"
        mock_settings.llm_provider = "anthropic"
        mock_settings.langfuse_public_key = None
        mock_settings.langfuse_secret_key = None
        mock_litellm.stream_chunk_builder.return_value = full_resp
        mock_litellm.RateLimitError = Exception
        mock_litellm.Timeout = TimeoutError

        events = await _drain_streaming(
            _call_llm_streaming(messages=[{"role": "user", "content": "hi"}])
        )

    text_events = [(k, v) for k, v in events if k == "text"]
    assert len(text_events) == 2
    assert text_events[0][1] == "Hello"
    assert text_events[1][1] == " world"

    done_events = [(k, v) for k, v in events if k == "done"]
    assert len(done_events) == 1


async def test_streaming_suppresses_text_when_tool_calls_appear():
    from investorai_mcp.llm.litellm_client import _call_llm_streaming

    tc_delta = MagicMock()
    chunks = [
        _make_stream_chunk(content=None, tool_call_delta=tc_delta),
        _make_stream_chunk(content="ignored text"),
    ]
    full_resp = _make_full_response("")

    with (
        patch("investorai_mcp.llm.litellm_client.acompletion", new=AsyncMock(return_value=_FakeStream(chunks))),
        patch("investorai_mcp.llm.litellm_client.litellm") as mock_litellm,
        patch("investorai_mcp.llm.litellm_client._log_usage", new=AsyncMock()),
        patch("investorai_mcp.llm.litellm_client.settings") as mock_settings,
    ):
        mock_settings.llm_api_key = "sk-test"
        mock_settings.llm_model = "claude-sonnet-4-20250514"
        mock_settings.llm_provider = "anthropic"
        mock_settings.langfuse_public_key = None
        mock_settings.langfuse_secret_key = None
        mock_litellm.stream_chunk_builder.return_value = full_resp
        mock_litellm.RateLimitError = Exception
        mock_litellm.Timeout = TimeoutError

        events = await _drain_streaming(
            _call_llm_streaming(messages=[{"role": "user", "content": "hi"}])
        )

    text_events = [k for k, v in events if k == "text"]
    assert len(text_events) == 0


async def test_streaming_raises_without_api_key():
    from investorai_mcp.llm.litellm_client import _call_llm_streaming

    import pytest

    with patch("investorai_mcp.llm.litellm_client.settings") as mock_settings:
        mock_settings.llm_api_key = None

        with pytest.raises(RuntimeError, match="No LLM API key"):
            await _drain_streaming(
                _call_llm_streaming(messages=[{"role": "user", "content": "test"}])
            )


async def test_streaming_logs_usage_on_success():
    from investorai_mcp.llm.litellm_client import _call_llm_streaming

    chunks = [_make_stream_chunk("Done.")]
    full_resp = _make_full_response("Done.")

    with (
        patch("investorai_mcp.llm.litellm_client.acompletion", new=AsyncMock(return_value=_FakeStream(chunks))),
        patch("investorai_mcp.llm.litellm_client.litellm") as mock_litellm,
        patch("investorai_mcp.llm.litellm_client._log_usage", new=AsyncMock()) as mock_log,
        patch("investorai_mcp.llm.litellm_client.settings") as mock_settings,
    ):
        mock_settings.llm_api_key = "sk-test"
        mock_settings.llm_model = "claude-sonnet-4-20250514"
        mock_settings.llm_provider = "anthropic"
        mock_settings.langfuse_public_key = None
        mock_settings.langfuse_secret_key = None
        mock_litellm.stream_chunk_builder.return_value = full_resp
        mock_litellm.RateLimitError = Exception
        mock_litellm.Timeout = TimeoutError

        await _drain_streaming(
            _call_llm_streaming(messages=[{"role": "user", "content": "hi"}], tool_name="agent_loop")
        )

    mock_log.assert_called_once()
    assert mock_log.call_args.kwargs["status"] == "success"
    assert mock_log.call_args.kwargs["tool_name"] == "agent_loop"
