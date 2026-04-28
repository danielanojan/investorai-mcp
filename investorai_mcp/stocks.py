"""
These 50 stocks will be used for the MCP. this is the single source of truth
Nothing outside this file should hardcode ticker symbols
"""

# dict with key= string (uppercase ticker names) - values : dict with keys: name, sector, exchange 
SUPPORTED_TICKERS: dict[str, dict[str, str]] = {
    # Technology
    "AAPL": {"name": "Apple Inc.", "sector": "Technology", "exchange": "NASDAQ"},
    "MSFT": {"name": "Microsoft Corporation", "sector": "Technology", "exchange": "NASDAQ"},
    "NVDA": {"name": "NVIDIA Corporation", "sector": "Technology", "exchange": "NASDAQ"},
    "GOOGL": {"name": "Alphabet Inc.", "sector": "Technology", "exchange": "NASDAQ"},
    "META": {"name": "Meta Platforms Inc.", "sector": "Technology", "exchange": "NASDAQ"},
    "AMZN": {"name": "Amazon.com Inc.", "sector": "Technology", "exchange": "NASDAQ"},
    "TSLA": {"name": "Tesla Inc.", "sector": "Technology", "exchange": "NASDAQ"},
    "AMD": {"name": "Advanced Micro Devices", "sector": "Technology", "exchange": "NASDAQ"},
    "INTC": {"name": "Intel Corporation", "sector": "Technology", "exchange": "NASDAQ"},
    "ORCL": {"name": "Oracle Corporation", "sector": "Technology", "exchange": "NYSE"},
    "CRM": {"name": "Salesforce Inc.", "sector": "Technology", "exchange": "NYSE"},
    "ADBE": {"name": "Adobe Inc.", "sector": "Technology", "exchange": "NASDAQ"},
    "QCOM": {"name": "Qualcomm Inc.", "sector": "Technology", "exchange": "NASDAQ"},
    "NFLX": {"name": "Netflix Inc.", "sector": "Technology", "exchange": "NASDAQ"},
    # Finance
    "JPM": {"name": "JPMorgan Chase & Co.", "sector": "Finance", "exchange": "NYSE"},
    "BAC": {"name": "Bank of America Corp.", "sector": "Finance", "exchange": "NYSE"},
    "GS": {"name": "Goldman Sachs Group Inc.", "sector": "Finance", "exchange": "NYSE"},
    "MS": {"name": "Morgan Stanley", "sector": "Finance", "exchange": "NYSE"},
    "V": {"name": "Visa Inc.", "sector": "Finance", "exchange": "NYSE"},
    "MA": {"name": "Mastercard Inc.", "sector": "Finance", "exchange": "NYSE"},
    "BRK-B": {"name": "Berkshire Hathaway B", "sector": "Finance", "exchange": "NYSE"},
    "AXP": {"name": "American Express Co.", "sector": "Finance", "exchange": "NYSE"},
    "WFC": {"name": "Wells Fargo & Co.", "sector": "Finance", "exchange": "NYSE"},
    "BLK": {"name": "BlackRock Inc.", "sector": "Finance", "exchange": "NYSE"},
    # Healthcare
    "JNJ": {"name": "Johnson & Johnson", "sector": "Healthcare", "exchange": "NYSE"},
    "UNH": {"name": "UnitedHealth Group Inc.", "sector": "Healthcare", "exchange": "NYSE"},
    "PFE": {"name": "Pfizer Inc.", "sector": "Healthcare", "exchange": "NYSE"},
    "ABBV": {"name": "AbbVie Inc.", "sector": "Healthcare", "exchange": "NYSE"},
    "MRK": {"name": "Merck & Co. Inc.", "sector": "Healthcare", "exchange": "NYSE"},
    "LLY": {"name": "Eli Lilly and Co.", "sector": "Healthcare", "exchange": "NYSE"},
    "TMO": {"name": "Thermo Fisher Scientific", "sector": "Healthcare", "exchange": "NYSE"},
    "AMGN": {"name": "Amgen Inc.", "sector": "Healthcare", "exchange": "NASDAQ"},
    # Consumer / Retail
    "WMT": {"name": "Walmart Inc.", "sector": "Consumer", "exchange": "NYSE"},
    "COST": {"name": "Costco Wholesale Corp.", "sector": "Consumer", "exchange": "NASDAQ"},
    "NKE": {"name": "Nike Inc.", "sector": "Consumer", "exchange": "NYSE"},
    "MCD": {"name": "McDonald's Corporation", "sector": "Consumer", "exchange": "NYSE"},
    "SBUX": {"name": "Starbucks Corporation", "sector": "Consumer", "exchange": "NASDAQ"},
    "TGT": {"name": "Target Corporation", "sector": "Consumer", "exchange": "NYSE"},
    "HD": {"name": "Home Depot Inc.", "sector": "Consumer", "exchange": "NYSE"},
    "DIS": {"name": "Walt Disney Co.", "sector": "Consumer", "exchange": "NYSE"},
    "PYPL": {"name": "PayPal Holdings Inc.", "sector": "Consumer", "exchange": "NASDAQ"},
    "SHOP": {"name": "Shopify Inc.", "sector": "Consumer", "exchange": "NYSE"},
    # Energy & Industrials
    "XOM": {
        "name": "Exxon Mobil Corporation",
        "sector": "Energy & Industrials",
        "exchange": "NYSE",
    },
    "CVX": {"name": "Chevron Corporation", "sector": "Energy & Industrials", "exchange": "NYSE"},
    "BA": {"name": "Boeing Company", "sector": "Energy & Industrials", "exchange": "NYSE"},
    "CAT": {"name": "Caterpillar Inc.", "sector": "Energy & Industrials", "exchange": "NYSE"},
    "GE": {"name": "GE Aerospace", "sector": "Energy & Industrials", "exchange": "NYSE"},
    "LMT": {"name": "Lockheed Martin Corp.", "sector": "Energy & Industrials", "exchange": "NYSE"},
    "NEE": {"name": "NextEra Energy Inc.", "sector": "Energy & Industrials", "exchange": "NYSE"},
    "ENPH": {"name": "Enphase Energy Inc.", "sector": "Energy & Industrials", "exchange": "NASDAQ"},
}

# lookup optimization : create a set of supported symbols for O(1) lookup
SUPPORTED_SYMBOLS: set[str] = set(SUPPORTED_TICKERS.keys())

# checks if specific stocks is there in allowed list. - Returns bool value [True/ False]
def is_supported(symbol: str) -> bool:
    return symbol.upper() in SUPPORTED_SYMBOLS

# function will return the dict (if ticker exists) with keys: name, sector, exchange. else returns None. 
# get function handles missing keys gracefully by returning None if the symbol is not found in the SUPPORTED_TICKERS dictionary.
def get_ticker_info(symbol: str) -> dict[str, str] | None:
    return SUPPORTED_TICKERS.get(symbol.upper())
