from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class OHLCVRecord:
    symbol: str
    date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    avg_price: float
    volume: int
    split_factor: float = 1.0


@dataclass
class NewsRecord:
    symbol: str
    headline: str
    source: str
    url: str
    published_at: datetime


@dataclass
class TickerInfoRecord:
    symbol: str
    name: str
    sector: str
    exchange: str
    currency: str
    market_cap: float | None = None
    shares_outstanding: int | None = None


# dataprovider adapter is an abstract base - there are three different datatypes
# OHLCVRecord, NewsRecord and TickerInfoRecord
class DataProviderAdapter(ABC):
    @abstractmethod
    async def fetch_ohlcv(self, symbol: str, period: str = "5y") -> list[OHLCVRecord]: ...

    @abstractmethod
    async def fetch_news(self, symbol: str, limit: int = 50) -> list[NewsRecord]: ...

    @abstractmethod
    async def fetch_ticker_info(self, symbol: str) -> TickerInfoRecord: ...
