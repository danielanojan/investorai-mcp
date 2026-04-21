"""
Chat history compressor for MCP


Keeps last 5 messages verbatim. 
Summarizes older messages into single compressed context block. 
Reduces token usage by 60-80% on long conversations. 


If the summarization LLM cal fails (no API key/ rate limited/ network error), the
function will return full history instead of crashing. The user's question will
still get answered, just without compression.

This trade off - never sacrifice correctness for cost optiomization.
"""
import logging

from investorai_mcp.llm.litellm_client import call_llm

logger = logging.getLogger(__name__)

# how many recent messages to keep vervatim. 
EXPLICIT_WINDOW = 5

#system prompt for the summarizaiton call
_SUMMARY_PROMPT = (
    "You are summarising conversation between the user and stock research assistant. "
    "Create a bried summary (2-4 sentences) what preserves: "
    "Which stocks were discussed, what data was requested, "
    "And any important context or preferences the user expressed. "
    "Be concise - this summary replaces the full history to save tokens"   
)


async def compress_history(
    messages: list[dict],
    session_hash: str = "anonymous",
    api_key: str | None = None,
) -> list[dict]:
    """
    Compress chat history to reduce token usage. 
    
    Keeps the last EXPLICIT_WINDOW messages verbatim. 
    Summarises all other messages into one system message. 
    
    Args:
        messages: Full conversation history as a list of 
        {"role": "..."}, "content": "..."} dicts.
        session_hash: For LLM usage tracking. 
        
    Returns:
        Compressed message list - same format but with fewer tokens. 
    """
    #short enough - no need to compress
    if len(messages) <= EXPLICIT_WINDOW: # +1 for system prompt
        return messages
    
    older = messages[:-EXPLICIT_WINDOW]
    recent = messages[-EXPLICIT_WINDOW:]
    
    #build a readable version of older message for sumarisation
    older_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in older
        if m['role'] in ("user", "assistant") 
    )
    try:
        summary = await call_llm(
            messages = [
                {"role": "system", "content": _SUMMARY_PROMPT},
                {"role": "user", "content": f"Summarise the following conversation history: \n\n{older_text}"},
            ],
            session_hash=session_hash,
            tool_name="history_compressor",
            max_tokens=200,
            api_key=api_key,
        )
        
        compressed = [
            {
                "role": "system",
                "content": f"[Earlier conversaiton summary]: {summary}"
            },
            *recent,
        ]
        
        logger.debug(
            "Compressed history from %d messages -> %d messages",
            len(messages),
            len(compressed),
        )
        return compressed
    
    except Exception as e:
        # if compression fails, return full history - never break the main flow
        logger.error("History compression failed, using full history: %s", str(e))
        return messages
    
def count_tokens_approx(messages: list[dict]) -> int:
    """
    Approximate token count for a list of messages. - 1 token ≈ 4 characters.
    Used for logging and monitoring not for hard limits. 
    """
    # very rough approximation: 1 token ~ 4 chars in English
    total_chars = sum(len(m.get("content", "")) for m in messages)
    return total_chars // 4

