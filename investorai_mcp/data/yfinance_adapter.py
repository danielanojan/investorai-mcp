import asyncio
from datetime import datetime
from functools import partial

import pandas as pd
import yfinance as yf

from investorai_mcp.data.base import(
    DataProviderAdapter,
    NewsRecord,
    OHLCVRecord,
    TickerInfoRecord,
)

"""
Yfinancer adapter class wraps yfinance library in async friendly way
Yfinance is syncronous and blocking library - the adapter class uses python's asyncio executor
pattern to run blocking cels in a thread pool without freezing the event loop

partial library - allows to pre-fill function arguments 


"""

#yfinance has own period format - we map to friendly readable format. 

PERIOD_MAP = {
    "1W": "5d",
    "1M": "1mo",
    "3M": "3mo",
    "6M": "6mo",
    "1Y": "1y",
    "3Y": "3y",
    "5Y": "5y",   
}

#creates a yf.Ticker and calls history() to get OHLCV(Open, High, Low, Close, Volume) data for the given symbol and period.
#auto adjust - will adjust prices for splits and dividends. 
def _sync_fetch_ohlcv(symbol: str, period: str) -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, auto_adjust=True)
    return df

# ticket info contains metadata like company_name, sector, market_cap etc. 
def _sync_fetch_info(symbol: str) -> dict:
    ticker = yf.Ticker(symbol)
    return ticker.info

"""
news will fetch 10 recent news articles related to the ticker. Each article contains 
an [id, content]
content is a dictionary with keys - 
dict_keys(['id', 'contentType', 'title', 'description', 
    'summary', 'pubDate', 'displayTime', 'isHosted', 'bypassModal', '
    previewUrl', 'thumbnail', 'provider', 'canonicalUrl', 'clickThroughUrl', 
    'metadata', 'finance', 'storyline'])
"""
#this function returns the raw news item dictionary. News can sometime fail or none. So a try catch is used to return empty list in case of any error.
def _sync_fetch_news(symbol: str) -> list[dict]:
    ticker = yf.Ticker(symbol)
    try:
        return ticker.news or []
    except Exception:
        return []


class YFinanceAdapter(DataProviderAdapter):
    #run_in_executor - runs blocking yfinanance call in a thread pool - so it does not block async event loop. 
    #run in execuror - only acccept a zero argument function . So partitial is used to prefill symbol and period arguments. 
    
    async def fetch_ohlcv(
        self, symbol: str, period: str = "5y"
    ) -> list[OHLCVRecord]:
        yf_period = PERIOD_MAP.get(period, period)
        
        loop = asyncio.get_event_loop() 
        #run-in_executor run
        df  = await loop.run_in_executor(
            None, partial(_sync_fetch_ohlcv, symbol, yf_period)
        )
        
        if df.empty:
            return []
        # loop over the dataframe and build the OHLCVRecord objects. 
        records = []
        for idx, row in df.iterrows():
            trade_date = idx.date() if hasattr(idx, "date") else idx
            open_ = float(row.get("Open", 0))
            high = float(row.get("High", 0))
            low = float(row.get("Low", 0))
            close = float(row.get("Close", 0))
            #auto_adjust= True means Close IS the adjusted Close - it calculates the closing price adjusted to splits and dividends.  
            adj_close = close
            avg_price = (open_ + high + low + adj_close) / 4
            volume = int(row.get("Volume", 0))
            
            if adj_close <=0:
                continue
            
            records.append(OHLCVRecord(
                symbol=symbol,
                date=trade_date,
                open=open_,
                high=high,
                low=low,
                close=close,
                adj_close=adj_close,
                avg_price=round(avg_price, 4),
                volume=volume,
            ))
            
        return records
    
    async def fetch_ticker_info(self, symbol: str) -> TickerInfoRecord:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(
            None, partial(_sync_fetch_info, symbol)
        )
        
        return TickerInfoRecord(
            symbol = symbol,
            name = info.get("longName") or info.get("shortName") or symbol,
            sector = info.get("sector") or "Unknown",
            exchange = info.get("exchange") or "Unknown",
            market_cap = info.get("marketCap"),
            shares_outstanding = info.get("sharesOutstanding"),
            currency = info.get("currency") or "USD",
            
        )
    
    # we can limit how many news articles to fetch. Here we limit at 50 articles. this can be varied by giving argument to fetch_news() method. 
    async def fetch_news(
        self, symbol: str, limit: int = 50
    ) -> list[NewsRecord]:
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(
            None, partial(_sync_fetch_news, symbol)
        )
        
        records = []
        for item in raw[:limit]:
            try:
                published_at = datetime.fromtimestamp(
                    item.get("providerPublishTime", 0)
                )
                records.append(NewsRecord(
                    symbol=symbol,
                    headline = item.get("title", ""),
                    source=item.get("publisher", ""),
                    url=item.get("link", ""),
                    published_at=published_at,
                ))
            except Exception:
                continue
                
        return records
    
    
