"""Unit test for chat history compressor."""
from unittest.mock import AsyncMock, patch


def make_messages(n: int) -> list[dict]:
    "Generate n alternating user/asistant messages."
    
    messages = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({"role": role,
                         "content": f"Message {i +1} about AAPL stock price history"
                        })
    return messages
    
# compress history ---------------------------
async def test_short_history_returned_unchanged():
    """Less than or equal to 5 meessages - no compression needed."""
    from investorai_mcp.llm.history import compress_history
    
    messages = make_messages(4)
    result = await compress_history(messages)
    
    assert result == messages #Messages should be unchanged if <= EXPLICIT_WINDOW
    
async def test_exactly_5_messages_returned_unchanged():
    """Exactly 5 messages - no compression needed."""
    from investorai_mcp.llm.history import compress_history
    
    messages =  make_messages(5)
    result = await compress_history(messages)
    
    assert result == messages # Messages should be unchanged if <= EXPLICIT_WINDOW
    
    
async def test_long_history_compressed_to_summary():
    """More than 5 messages - should compress older messages into a summary."""
    from investorai_mcp.llm.history import EXPLICIT_WINDOW, compress_history
    
    messages =  make_messages(10)
    
    with patch("investorai_mcp.llm.history.call_llm", new=AsyncMock(return_value="User discussed AAPL prices.")):
        result = await compress_history(messages)
    
    #should be summary + last 5 messages
    assert len(result) == EXPLICIT_WINDOW + 1 # Result should contain summary + last EXPLICIT_WINDOW messages
    
    
async def test_last_5_messages_preserved_verbatim():
    """ The last EXPLICIT_WINDOW messages must be identical to originals."""
    from investorai_mcp.llm.history import EXPLICIT_WINDOW, compress_history
    
    messages = make_messages(10)
    last_5 = messages[-EXPLICIT_WINDOW:]
    
    with patch("investorai_mcp.llm.history.call_llm", 
               new=AsyncMock(return_value="Summary of earlier messages")):
        result = await compress_history(messages)
        
    #last 2 in result match with the 5 of originals exactly. 
    assert result[-EXPLICIT_WINDOW:] == last_5 # #Last EXPLICIT_WINDOW messages should be unchanged
    
async def test_summary_is_first_message():
    """The compressed summary becomes the first message in the list"""
    from investorai_mcp.llm.history import compress_history
    
    messages = make_messages(10)
    summary_text = "User asked about AAPL and TSLA price history."
    
    with patch("investorai_mcp.llm.history.call_llm",
                new=AsyncMock(return_value=summary_text)):
          result = await compress_history(messages)
          
    assert result[0]["role"] == "system" #First message should be system role with summary
    assert summary_text in result[0]["content"]
    
async def test_summary_contains_earlier_conversation_label():
    from investorai_mcp.llm.history import compress_history
    
    messages = make_messages(10)
    
    with patch("investorai_mcp.llm.history.call_llm",
                new=AsyncMock(return_value="User discussed stocks.")):
          result = await compress_history(messages)
    
    assert "[Earlier conversaiton summary]" in result[0]["content"] #Summary message should contain label indicating it's a summary of earlier conversation
    

async def test_compression_fails_gracefully():
    """If call_llm fails, return full history unchanged."""
    from investorai_mcp.llm.history import compress_history
    
    messages = make_messages(10)
    
    with patch("investorai_mcp.llm.history.call_llm",
                new=AsyncMock(side_effect=Exception("LLM unavailable"))):
          result = await compress_history(messages)
    
    #should resullt original full history, not crash
    assert result == messages
    
async def test_compression_reduces_message_count():
    from investorai_mcp.llm.history import compress_history
    
    messages = make_messages(20)
    
    with patch("investorai_mcp.llm.history.call_llm",
                new=AsyncMock(return_value="Summary of 15 earlier messages.")):
          result = await compress_history(messages)
    
    assert len(result) < len(messages) #Compressed history should have fewer messages than original
    
# ----- Count_tokens_approx ----------------------------

def test_token_count_empty():
    from investorai_mcp.llm.history import count_tokens_approx
    
    assert count_tokens_approx([]) == 0 #Empty message list should have 0 tokens
    
def test_token_count_approximate():
    from investorai_mcp.llm.history import count_tokens_approx
    
    messages = [{"role": "user", "content": "a" * 400}]
    # 400 chars / 4 = 100 tokens approx
    assert count_tokens_approx(messages) == 100 #Token count should be approximately chars
    
def test_token_count_multiple_messages():
    from investorai_mcp.llm.history import count_tokens_approx
    
    messages = [
        {"role": "user", "content": "a" * 200},
        {"role": "assistant", "content": "b" * 200}
    ]
    
    # 400 chars total / 4 = 100 tokens approx
    assert count_tokens_approx(messages) == 100 #"Token count should be approximately total