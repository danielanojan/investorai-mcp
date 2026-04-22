"""
LiteLLM wrapper and Langfuse monitoring

Every LLM call in investorAI goes through this module.
Handles: BYOK routing, Langfuse tracing, llm_usage_log writing,
error handling and token counting
"""

import time
import logging
import contextlib
from datetime import datetime, timezone

import litellm
from litellm import acompletion

from investorai_mcp.config import settings

logger = logging.getLogger(__name__)

### Langfuse setup (4.x SDK — credentials from settings, not env vars)

_langfuse = None

if settings.langfuse_public_key and settings.langfuse_secret_key:
    try:
        from langfuse import Langfuse
        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.debug("Langfuse monitoring enabled")
    except Exception as e:
        logger.warning("Langfuse init failed: %s", e)


def _get_langfuse_handler():
    """Return the Langfuse client if configured, None otherwise."""
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return None
    return _langfuse


def get_langfuse():
    """Return the Langfuse client instance, or None if not configured."""
    return _langfuse


def lf_span(name: str, as_type: str = "span", **kwargs):
    """Return a Langfuse context-manager observation, or a no-op if Langfuse is not configured.

    Use as::

        with lf_span("get_price_history", input={"symbol": symbol, "range": range}):
            ...

    Child observations (e.g. the LLM generation in call_llm) are automatically
    nested under the innermost active span via Langfuse's contextvars propagation.
    """
    if _langfuse:
        return _langfuse.start_as_current_observation(as_type=as_type, name=name, **kwargs)
    return contextlib.nullcontext()
    
# Log to DB ----------------------------------------

async def _log_usage(
    session_hash: str,
    tool_name: str | None,
    tokens_in: int,
    tokens_out: int,
    latency_ms: int,
    status: str,
) -> None:
    """ Write one row to llm_usage_log table"""
    from investorai_mcp.db import AsyncSessionLocal
    from investorai_mcp.db.models import LLMUsageLog
    
    async with AsyncSessionLocal() as session:
        entry = LLMUsageLog(
            session_hash=session_hash,
            provider = settings.llm_provider,
            model = settings.llm_model,
            tool_name=tool_name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            status=status,
            ts = datetime.now(timezone.utc),
        )
        session.add(entry)
        await session.commit()
        
        
#### Low-level call — shared by call_llm and run_agent_loop --------------------------------

async def _call_llm_raw(
    messages: list[dict],
    session_hash: str = "anonymous",
    tool_name: str | None = None,
    max_tokens: int = 500,
    api_key: str | None = None,
    tools: list | None = None,
    tool_choice: str = "auto",
):
    """
    Execute one LLM call with full observability (Langfuse + DB usage log).
    Returns the raw LiteLLM response object so callers can inspect tool_calls
    or extract text depending on their needs.

    Raises RuntimeError on auth failure, rate limit, timeout, or other errors.
    """
    resolved_key = api_key or settings.llm_api_key
    if not resolved_key:
        raise RuntimeError("No LLM API key configured. "
                           "Please set llm_api_key in .env file.")

    call_kwargs: dict = {
        "model": settings.llm_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "api_key": resolved_key,
    }
    if tools:
        call_kwargs["tools"] = tools
        call_kwargs["tool_choice"] = tool_choice

    _obs = None
    _start_ns: int = time.time_ns()
    if _langfuse:
        try:
            _obs = _langfuse.start_observation(
                as_type="generation",
                name=tool_name or "llm-call",
                model=settings.llm_model,
                input=messages,
                metadata={"session_hash": session_hash},
            )
        except Exception as lf_err:
            logger.warning("Langfuse start_observation failed: %s", lf_err)

    start = time.monotonic()
    status = "success"
    tokens_in = 0
    tokens_out = 0
    text = ""

    try:
        response = await acompletion(**call_kwargs)

        if hasattr(response, "usage") and response.usage:
            tokens_in = response.usage.prompt_tokens or 0
            tokens_out = response.usage.completion_tokens or 0

        text = response.choices[0].message.content or ""
        return response

    except litellm.RateLimitError as e:
        status = "rate_limited"
        logger.warning("LLM call rate limited: %s", str(e))
        raise RuntimeError(f"LLM rate limited: {e}") from e

    except litellm.Timeout as e:
        status = "timeout"
        logger.error("LLM call timed out: %s", str(e))
        raise RuntimeError(f"LLM call timed out: {e}") from e

    except Exception as e:
        status = "error"
        logger.error("LLM call failed: %s", str(e))
        raise RuntimeError(f"LLM call failed: {e}") from e

    finally:
        latency_ms = int((time.monotonic() - start) * 1000)
        _end_ns: int = _start_ns + latency_ms * 1_000_000

        if _obs:
            try:
                _obs.update(
                    output=text if status == "success" else None,
                    usage_details={"input": tokens_in, "output": tokens_out},
                    status_message=None if status == "success" else status,
                )
            except Exception as lf_err:
                logger.warning("Langfuse update failed: %s", lf_err)
            finally:
                try:
                    _obs.end(end_time=_end_ns)
                    _langfuse.flush()
                except Exception as lf_err:
                    logger.warning("Langfuse end/flush failed: %s", lf_err)

        try:
            await _log_usage(
                session_hash=session_hash,
                tool_name=tool_name,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
                status=status,
            )
        except Exception as log_err:
            logger.warning("Failed to log LLM usage: %s", log_err)


#### Public text-only wrapper --------------------------------

async def call_llm(
    messages: list[dict],
    session_hash: str = "anonymous",
    tool_name: str | None = None,
    max_tokens: int = 500,
    api_key: str | None = None,
) -> str:
    """Send messages to LLM and return response text. All observability handled."""
    response = await _call_llm_raw(
        messages=messages,
        session_hash=session_hash,
        tool_name=tool_name,
        max_tokens=max_tokens,
        api_key=api_key,
    )
    return response.choices[0].message.content or ""
        
    
    
    
    