from investorai_mcp.stocks import (
    SUPPORTED_SYMBOLS,
    SUPPORTED_TICKERS,
    get_ticker_info,
    is_supported,
)


def test_exactly_50_tickers():
    assert len(SUPPORTED_TICKERS) == 50
    
    
def test_all_required_fields_present():
    for symbol, info in SUPPORTED_TICKERS.items():
        assert "name" in info, f"Ticker {symbol} is missing 'name'"
        assert "sector" in info, f"Ticker {symbol} is missing 'sector'"
        assert "exchange" in info, f"Ticker {symbol} is missing 'exchange'"
        

def test_all_exchanges_valid():
    valid_exchanges = {"NASDAQ", "NYSE"}
    for symbol, info in SUPPORTED_TICKERS.items():
        assert info["exchange"] in valid_exchanges, f"{symbol} has invalid exchange"
        

def test_all_sectors_valid():
    valid_sectors = {
        "Technology",
        "Finance",
        "Healthcare",
        "Consumer",
        "Energy & Industrials",
        
    }
    for symbol, info in SUPPORTED_TICKERS.items():
        assert info["sector"] in valid_sectors, f"{symbol} has invalid sector"
    

def test_sector_counts():
    from collections import Counter
    counts = Counter(info["sector"] for info in SUPPORTED_TICKERS.values())
    assert counts["Technology"] == 14
    assert counts["Finance"] == 10
    assert counts["Healthcare"] == 8
    assert counts["Consumer"] == 10
    assert counts["Energy & Industrials"] == 8
    
    
def test_is_supported_known_ticker():
    assert is_supported("AAPL") is True
    assert is_supported("TSLA") is True
    assert is_supported("NVDA") is True
    

def test_is_supported_case_insensitive():
    assert is_supported("aapl") is True
    assert is_supported("Tsla") is True
    assert is_supported("nvDa") is True
    
def test_is_supported_unknown_ticker():
    assert is_supported("FAKE") is False
    assert is_supported("XYZ") is False
    assert is_supported("1234") is False
    assert is_supported("") is False

def test_get_ticker_info_known_ticker():
    info = get_ticker_info("AAPL")
    assert info is not None
    assert info["name"] == "Apple Inc."
    assert info["sector"] == "Technology"
    assert info["exchange"] == "NASDAQ"
    
    
def test_get_ticker_info_unknown_returns_none():
    assert get_ticker_info("FAKECROP") is None

def test_supported_symbols_set_matches_dict():
    assert SUPPORTED_SYMBOLS == set(SUPPORTED_TICKERS.keys())

def test_brk_b_included():
    # BRK-B is the most widely held retail proxy - must be in the universe
    assert "BRK-B" in SUPPORTED_TICKERS
    

