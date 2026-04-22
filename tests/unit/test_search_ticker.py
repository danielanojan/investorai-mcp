import pytest


#pytest decorator - automatically applies a fixture to every test in the scope/ file. No need to explicitly pass it as a paramter. 
#pytest.fixture - instead of repeating the setup code every time - you define it as a fixture and inject into all the tests which need it. 
@pytest.fixture(autouse=True)
def register_tools():
    from investorai_mcp.server import _register_tools
    _register_tools()
    
    
#
async def test_search_by_exact_symbol():
    from investorai_mcp.tools.search_ticker import search_ticker
    result = await search_ticker("AAPL")
    assert result["total"] == 1
    assert result["matches"][0]["symbol"] == "AAPL"
    assert result["matches"][0]["name"] == "Apple Inc."

async def test_search_by_partial_symbol():
    from investorai_mcp.tools.search_ticker import search_ticker
    result = await search_ticker("NV")
    symbols = [m["symbol"] for m in result["matches"]]
    assert "NVDA" in symbols
    
    
async def test_search_by_company_name():
    from investorai_mcp.tools.search_ticker import search_ticker
    result = await search_ticker("Apple")
    symbols = [m["symbol"] for m in result["matches"]]
    assert "AAPL" in symbols
    
async def test_search_case_insensitive():
    from investorai_mcp.tools.search_ticker import search_ticker
    r1 = await search_ticker("apple")
    r2 = await search_ticker("APPLE")
    r3 = await search_ticker("aPpLe")
    assert r1["total"] == r2["total"] == r3["total"]
    
    
async def test_search_by_sector_word():
    from investorai_mcp.tools.search_ticker import search_ticker
    result = await search_ticker("tech")
    # "tech" appears in Technology sector AND in keywords like "fintech"
    # so results may include finance stocks — just verify we got results
    assert result["total"] >= 1
    symbols = [m["symbol"] for m in result["matches"]]
    # All 14 technology stocks should be in results
    assert "AAPL" in symbols
    assert "MSFT" in symbols
    assert "NVDA" in symbols
        
async def test_search_no_match_return_empty():
    from investorai_mcp.tools.search_ticker import search_ticker
    result = await search_ticker("nonexistentcompany")
    assert result["total"] == 0
    assert result["matches"] == []
    
async def test_search_returns_correct_fields():
    from investorai_mcp.tools.search_ticker import search_ticker
    result = await search_ticker("TSLA")
    match = result["matches"][0]
    assert "symbol" in match
    assert "name" in match
    assert "sector" in match
    assert "exchange" in match
    
async def test_search_returns_metadata():
    from investorai_mcp.tools.search_ticker import search_ticker
    result = await search_ticker("AAPL")
    assert "query" in result
    assert "total" in result
    assert "supported_universe_size" in result
    assert result["supported_universe_size"] == 50
    
async def test_search_partial_name_returns_multiple():
    from investorai_mcp.tools.search_ticker import search_ticker
    result = await search_ticker("bank")
    #bank of americal contains bank
    symbols = [m["symbol"] for m in result["matches"]]
    assert "BAC" in symbols
    
async def test_search_whitespace_handled():
    from investorai_mcp.tools.search_ticker import search_ticker
    result = await search_ticker("  AAPL  ")
    assert result["total"] == 1
