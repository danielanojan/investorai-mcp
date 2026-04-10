import pytest

def test_mcp_instance_created():
    from investorai_mcp.server import mcp
    assert mcp is not None
    assert mcp.name == "investorai"
    
async def test_tools_register_without_error():
    from investorai_mcp.server import mcp, _register_tools
    _register_tools()
    
    tools = await mcp.list_tools()
    assert len(tools) >=1 
    
async def test_search_ticker_tool_is_registered():
    from investorai_mcp.server import _register_tools, mcp
    _register_tools()
    tool_names = [t.name for t in await mcp.list_tools()]
    assert "search_ticker" in tool_names
    