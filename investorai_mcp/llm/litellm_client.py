"""
LiteLLM wrapper and Langfuse monitoring

EveryLLM call in investorAI goes through this module. 
Handles: BOYK routing, Langfuse tracing llm_usage_lig writing, 
error handling and token counting
"""

import time
import logging
from datetime import datetime, timezone

import litellm
from litellm import acompletion

from investorai_mcp.config import settings

logger = logging.getLogger(__name__)

### Langfuse setup

def _get_langfuse_handler():
    """
    Returns a langfuse callback handler if keys are configured. 
    Returns None if langfuse is not setup - monitoring is optional. 
    LLM can still work without langfuse. 
    """
    if not settings.langfuse_public_key or not settings.langfuse_private_key:
        logger.debug("Langfuse keys not configured - skipping monitoring")
        return None
    
    try: 
        from langfuse.callback import CallbackHandler
        return CallbackHandler(
            public_key=settings.langfuse_public_key,
            private_key=settings.langfuse_private_key,
            host=settings.langfuse_host,
        )
    except Exception as e:
        logger.warning("Langfuse init failed: %s", str(e))
        return None
    
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
        
        
#### Main call function --------------------------------

async def call_llm(
    messages: list[dict], 
    session_hash : str = "anonymous",
    tool_name: str | None = None,
    max_tokens: int = 500,
) -> dict:
    """
    Send messages to the LLM and return the response text
    
    Uses LiteLLM to route to any provider. Logs every call to 
    Langfuse (if configured) and to the llm_usage_log in the DB. 
    
    Args: 
        messages : List of { role: "system|user|assistant", content: "text" } dicts
        session_hash : Anonymous session identifier for usage tracking
        tool_name : Which MCP tool triggered for this call (For langfuse tracing)
        max_tokens : Maximum number of tokens to generate. Default is 500. Adjust based on expected response length.
        
    Returns:
        Response text as a plain string
    
    Raises: 
        RuntimeError: if no API key is configured or LLM call fails. 
    """
    if not settings.llm_api_key:
        raise RuntimeError("No LLM API key configured. "
                           "Please set llm_api_key in .env file.")
    
    #Build kwargs for litellm
    call_kwargs = {
        "model": settings.llm_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "api_key": settings.llm_api_key,
    }
    
    #Add langfuse callback if configured
    handler = _get_langfuse_handler()
    if handler:
        call_kwargs["callbacks"] = [handler]
        call_kwargs["metadata"] = {
            "session_hash": session_hash,
            "tool_name": tool_name,
        }
        
    # make the call and track timing
    start = time.monotonic()
    status = "success"
    tokens_in = 0
    tokens_out = 0
    
    try:
        response = await acompletion(**call_kwargs)
        
        #extract token counts from response
        if hasattr(response, "usage") and response.usage:
            tokens_in = response.usage.prompt_tokens or 0
            tokens_out = response.usage.completion_tokens or 0
        
        text = response.choices[0].message.content or ""
        
        return text
    
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
        
    
    
    
    