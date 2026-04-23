import asyncio
import logging
from datetime import datetime
from functools import partial

import pandas as pd
import yfinance as yf
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from investorai_mcp.data.base import (
    DataProviderAdapter,
    NewsRecord,
    OHLCVRecord,
    TickerInfoRecord,
)

logger = logging.getLogger(__name__)

# Cap concurrent outbound Yahoo Finance calls — broad agent queries (50 stocks)
# would otherwise fire 50 simultaneous HTTP requests and trigger rate limiting.
_YF_SEMAPHORE = asyncio.Semaphore(5)

PERIOD_MAP = {
    "1W": "5d",
    "1M": "1mo",
    "3M": "3mo",
    "6M": "6mo",
    "1Y": "1y",
    "3Y": "3y",
    "5Y": "5y",
}


# ---------------------------------------------------------------------------
# Sync fetch functions — run in thread pool via run_in_executor.
# Decorated with tenacity so transient network errors are retried automatically
# before the error propagates to the caller.
# ---------------------------------------------------------------------------


@retry(
    retry=retry_if_exception_type((OSError, ConnectionError, TimeoutError)),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _sync_fetch_ohlcv(symbol: str, period: str) -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    return ticker.history(period=period, auto_adjust=True)


@retry(
    retry=retry_if_exception_type((OSError, ConnectionError, TimeoutError)),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _sync_fetch_info(symbol: str) -> dict:
    ticker = yf.Ticker(symbol)
    return ticker.info


def _sync_fetch_news(symbol: str) -> list[dict]:
    ticker = yf.Ticker(symbol)
    try:
        return ticker.news or []
    except Exception:
        return []


class YFinanceAdapter(DataProviderAdapter):
    async def fetch_ohlcv(self, symbol: str, period: str = "5y") -> list[OHLCVRecord]:
        yf_period = PERIOD_MAP.get(period, period)
        loop = asyncio.get_event_loop()

        async with _YF_SEMAPHORE:
            df = await loop.run_in_executor(None, partial(_sync_fetch_ohlcv, symbol, yf_period))

        if df.empty:
            return []

        records = []
        for idx, row in df.iterrows():
            trade_date = idx.date() if hasattr(idx, "date") else idx
            open_ = float(row.get("Open", 0))
            high = float(row.get("High", 0))
            low = float(row.get("Low", 0))
            close = float(row.get("Close", 0))
            adj_close = close  # auto_adjust=True means Close IS the adjusted close
            avg_price = (open_ + high + low + adj_close) / 4
            volume = int(row.get("Volume", 0))

            if adj_close <= 0:
                continue

            records.append(
                OHLCVRecord(
                    symbol=symbol,
                    date=trade_date,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    adj_close=adj_close,
                    avg_price=round(avg_price, 4),
                    volume=volume,
                )
            )

        return records

    async def fetch_ticker_info(self, symbol: str) -> TickerInfoRecord:
        loop = asyncio.get_running_loop()

        async with _YF_SEMAPHORE:
            info = await loop.run_in_executor(None, partial(_sync_fetch_info, symbol))

        return TickerInfoRecord(
            symbol=symbol,
            name=info.get("longName") or info.get("shortName") or symbol,
            sector=info.get("sector") or "Unknown",
            exchange=info.get("exchange") or "Unknown",
            market_cap=info.get("marketCap"),
            shares_outstanding=info.get("sharesOutstanding"),
            currency=info.get("currency") or "USD",
        )

    async def fetch_news(self, symbol: str, limit: int = 50) -> list[NewsRecord]:
        loop = asyncio.get_running_loop()

        async with _YF_SEMAPHORE:
            raw = await loop.run_in_executor(None, partial(_sync_fetch_news, symbol))

        records = []
        for item in raw[:limit]:
            try:
                content = item.get("content") or item
                headline = content.get("title", "")

                provider = content.get("provider", {})
                source = ""
                if isinstance(provider, dict):
                    source = provider.get("displayName", "") or ""
                source = source or content.get("publisher", "") or item.get("publisher", "")

                canonical = content.get("canonicalUrl") or {}
                clickthrough = content.get("clickThroughUrl") or {}
                url = canonical.get("url") or clickthrough.get("url") or item.get("link", "")

                pub_date = content.get("pubDate", "")
                if pub_date:
                    published_at = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                else:
                    published_at = datetime.fromtimestamp(item.get("providerPublishTime", 0))

                records.append(
                    NewsRecord(
                        symbol=symbol,
                        headline=headline,
                        source=source,
                        url=url,
                        published_at=published_at,
                    )
                )
            except Exception:  # noqa: S112
                continue

        return records
