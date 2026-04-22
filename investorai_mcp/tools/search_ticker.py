from fastmcp import Context

from investorai_mcp.server import mcp
from investorai_mcp.stocks import SUPPORTED_TICKERS

# Keywords for conceptual searches — things users type that don't
# appear in company names but describe what the company does.
# Keeps search useful without needing embeddings or ML models.
TICKER_KEYWORDS: dict[str, str] = {
    "AAPL":  "iphone ipad mac laptop smartphone tablet consumer electronics",
    "MSFT":  "cloud azure office windows software enterprise copilot",
    "NVDA":  "gpu semiconductor chip ai artificial intelligence data centre gaming graphics",
    "GOOGL": "search advertising youtube maps android browser cloud",
    "META":  "social media facebook instagram whatsapp advertising",
    "AMZN":  "ecommerce cloud aws marketplace retail delivery prime",
    "TSLA":  "electric vehicle ev car autonomous driving battery energy solar",
    "AMD":   "semiconductor gpu cpu chip processor gaming data centre",
    "INTC":  "semiconductor cpu processor chip intel server",
    "ORCL":  "database cloud enterprise software erp",
    "CRM":   "crm sales cloud customer relationship saas enterprise",
    "ADBE":  "design creative software photoshop pdf cloud",
    "QCOM":  "semiconductor mobile chip wireless 5g smartphone",
    "NFLX":  "streaming video entertainment subscription content",
    "JPM":   "bank investment banking financial services credit card",
    "BAC":   "bank retail banking financial services loans mortgage",
    "GS":    "investment bank trading financial advisory wall street",
    "MS":    "investment bank wealth management financial advisory",
    "V":     "payment network credit card digital transactions fintech",
    "MA":    "payment network credit card digital transactions fintech",
    "BRK-B": "insurance investment conglomerate berkshire warren buffett",
    "AXP":   "credit card payment travel rewards financial services",
    "WFC":   "bank retail banking mortgage financial services loans",
    "BLK":   "asset management investment etf fund blackrock",
    "JNJ":   "pharmaceutical medical device consumer health drugs",
    "UNH":   "health insurance managed care medical benefits",
    "PFE":   "pharmaceutical drugs vaccine biotech medicine",
    "ABBV":  "pharmaceutical biotech drugs arthritis immunology",
    "MRK":   "pharmaceutical drugs vaccine medicine oncology",
    "LLY":   "pharmaceutical diabetes obesity weight loss drugs",
    "TMO":   "laboratory scientific instrument biotech research",
    "AMGN":  "biotech pharmaceutical drugs oncology inflammation",
    "WMT":   "retail supermarket grocery discount store ecommerce",
    "COST":  "wholesale retail warehouse membership grocery",
    "NKE":   "sportswear shoes athletic apparel footwear",
    "MCD":   "fast food restaurant burger franchise",
    "SBUX":  "coffee cafe beverage restaurant",
    "TGT":   "retail department store discount grocery",
    "HD":    "home improvement hardware tools construction diy",
    "DIS":   "entertainment media theme park streaming disney",
    "PYPL":  "payment fintech digital wallet checkout online",
    "SHOP":  "ecommerce platform merchant online store retail",
    "XOM":   "oil gas energy petroleum refinery fossil fuel",
    "CVX":   "oil gas energy petroleum refinery fossil fuel",
    "BA":    "aerospace aircraft defense aviation plane boeing",
    "CAT":   "construction machinery equipment industrial mining",
    "GE":    "aerospace jet engine industrial aviation defence",
    "LMT":   "defence military aerospace weapon lockheed",
    "NEE":   "renewable energy utility solar wind electricity",
    "ENPH":  "solar energy renewable electricity inverter",
}




@mcp.tool()
async def search_ticker(
    query: str,
    ctx: Context | None = None,
    ) -> dict:
    """search for supported stock tickers by name, sector or description.
    
    use this tool first when the user mentions a company name or partial symbol or sector or concept. 
    Return all tickers whose symbol, company name, sector, or description contains the query string.
    
    Only searches the 50-stock MVP universe. Do not use for crypto, ETFs or international stocks - these are not supported.
    
    Args:
        query: Company name, ticker symbol, sector, or concept.
               Examples: "apple", "AAPL", "electric car", "semiconductor",
               "payment", "bank", "streaming", "cloud"
            
    Returns:
        Dict with matches list (symbol, name, sector, exchange) and total count. 
    
    """
    q = query.strip().upper()
    
    if not q:
        return {
            "query": query, 
            "matches" : [],
            "total": 0,
            "supported_universe_size": len(SUPPORTED_TICKERS),
        }
    
    matches = []
    for symbol, info in SUPPORTED_TICKERS.items():
        keywords = TICKER_KEYWORDS.get(symbol, "").upper()
        if (
            q in symbol
            or q in info["name"].upper()
            or q in info["sector"].upper()
            or q in keywords
        ):
            matches.append({
                "symbol": symbol,
                "name": info["name"],
                "sector": info["sector"],
                "exchange": info["exchange"],
            })
    return {
        "query": query,
        "matches": matches,
        "total": len(matches),
        "supported_universe_size": len(SUPPORTED_TICKERS),
    }