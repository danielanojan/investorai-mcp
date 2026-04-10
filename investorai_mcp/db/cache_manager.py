import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generic, TypeVar

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from investorai_mcp.data.base import DataProviderAdapter, OHLCVRecord
from investorai_mcp.db.models import CacheMetadata, PriceHistory, Ticker

logger = logging.getLogger(__name__)

T = TypeVar("T")

TTL_SECONDS = {
    "price_history" : 86400,   #24 hours
    "news": 14400,         #4 hours
    "ticker_info": 604800, #7 days
    "sentiment": 14400,   #4 hours
}

#A generic wrapper around any returned data. Generic[T] means it can wrap any type — CacheResult[list[PriceHistory]], CacheResult[list[NewsRecord]], etc. 
# It carries not just the data but metadata about it: how old is it, where did it come from, is it stale?
@dataclass
class CacheResult(Generic[T]):
    data: T
    is_stale: bool
    data_age_hours: float
    provider_used: str | None
    
    def with_staleness_warning(self, age_hours: float) -> "CacheResult[T]":
        return CacheResult(
            data=self.data,
            is_stale=True,
            data_age_hours=age_hours,
            provider_used=self.provider_used,
        )
        
class CacheManager:
    def __init__(self, session: AsyncSession, adapter: DataProviderAdapter):
        self._session = session
        self._adapter = adapter
        
    ###### ------ PUBLIC API ----------------------------------
    
    async def get_prices(
        self, 
        symbol: str, 
        period: str ="1Y"
    ) -> CacheResult[list[PriceHistory]]:
        #This is the main method users of this class call. It implements a stale-while-revalidate caching strategy:
        meta = await self._get_or_create_meta(symbol, "price_history")
        
        age_hours = self._age_hours(meta.last_fetched)
        is_fresh = not meta.is_stale and age_hours < (
            TTL_SECONDS["price_history"] / 3600
        )
        
        # First it gets the cache metadata record for this symbol. Then it calculates how old the data is and whether it's still within the TTL window.
        if is_fresh:
            #If fresh — read from DB and return immediately. No network call needed.
            rows = await self._read_prices(symbol, period)
            return CacheResult(
                data=rows,
                is_stale=False,
                data_age_hours=age_hours,
                provider_used=meta.provider_used,
            )
            
        #If stale — this is the clever part. It returns the old data immediately so the user isn't waiting, then kicks off a background refresh task. 
        # The next request will get fresh data. This is the classic stale-while-revalidate pattern — prioritise speed over freshness.
        rows = await self._read_prices(symbol, period)
        asyncio.create_task(
            self._refresh_prices(symbol, meta)
        )
        return CacheResult(
            data=rows,
            is_stale=True,
            data_age_hours=age_hours,
            provider_used=meta.provider_used
        )
    # Unlike get_prices, this waits for the refresh to complete before returning. 
    # sed when you explicitly need guaranteed fresh data — e.g. a manual refresh button. 
    # Notice it fetches "5Y" of data to maximise the cache fill.
    async def force_refresh_prices(self, symbol: str) -> CacheResult[list[PriceHistory]]:
        meta = await self._get_or_create_meta(symbol, "price_history")
        await self._refresh_prices(symbol, meta)
        rows = await self._read_prices(symbol, "5Y")
        meta = await self._get_or_create_meta(symbol, "price_history")
        return CacheResult(
            data=rows,
            is_stale=False,
            data_age_hours=0.0,
            provider_used=meta.provider_used
        )
        
    
    async def ensure_ticker_exists(self, symbol: str) -> Ticker | None:
        result = await self._session.get(Ticker, symbol)
        if result:
            return result # if ticker already exists in DB, return it immediately
    
        from investorai_mcp.stocks import get_ticker_info
        info = get_ticker_info(symbol)
        if not info:
            return None # not in our supported list
        
        ticker = Ticker(
            symbol=symbol,
            name=info["name"],
            sector=info["sector"],
            exchange=info["exchange"],
            is_supported=True,
        )
        self._session.add(ticker)
        await self._session.commit()
        return ticker
    
    
    ######## Private : meta -----------------------------
    async def _get_or_create_meta(
        self, symbol: str, data_type: str
    ) -> CacheMetadata:
        stmt = select(CacheMetadata).where(
            CacheMetadata.symbol == symbol,
            CacheMetadata.data_type == data_type,
        )
        result = await self._session.execute(stmt)
        meta = result.scalar_one_or_none()
        
        if meta is None:
            meta = CacheMetadata(
                symbol=symbol,
                data_type=data_type,
                ttl_seconds=TTL_SECONDS[data_type],
                is_stale=True,
                fetch_count=0,
                error_count=0,
            )
            self._session.add(meta)
            await self._session.commit()
            await self._session.refresh(meta)
            
        return meta
    
    ############# Private: read --------------------------
    async def _read_prices(
        self, symbol: str, period: str
    ) -> list[PriceHistory]:
        from datetime import date, timedelta
        
        cutoff = self._period_to_cutoff(period)
        stmt = (
            select(PriceHistory)
            .where(
                PriceHistory.symbol == symbol,
                PriceHistory.date >=cutoff,
            )
            .order_by(PriceHistory.date.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
    
    ####### Private : refresh --------------------------   
    async def _refresh_prices(
        self, symbol: str, meta: CacheMetadata
    ) -> None:
        logger.info("Refreshing price history for %s", symbol)
        try:
            records: list[OHLCVRecord] = await self._adapter.fetch_ohlcv(
                symbol, period="5y"
            ) 
            if not records:
                logger.warning("No OHLCV data returned for %s", symbol)
                await self._update_meta_error(meta)
                return
            
            await self._upsert_prices(symbol, records)
            await self._update_meta_success(meta, provider="yfinance")
            logger.info("refreshed %d price records for %s", len(records), symbol)
        
        except Exception as exc:
            logger.error("Failed to refresh prices for %s: %s", symbol, exc)
            await self._update_meta_error(meta)
            
            
    async def _upsert_prices(
        self, symbol: str, records: list[OHLCVRecord]
    ) -> None:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        
        for record in records:
            stmt = sqlite_insert(PriceHistory).values(
                symbol=symbol,
                date=record.date,
                open=record.open,
                high=record.high,
                low=record.low, 
                close=record.close,
                adj_close=record.adj_close,
                avg_price=record.avg_price,
                volume=record.volume,
                split_factor=record.split_factor,
                fetched_at=datetime.now(timezone.utc)
            )
            stmt = stmt.on_conflict_do_update(
                index_elements = ["symbol", "date"],
                set_={
                    "adj_close": stmt.excluded.adj_close,
                    "avg_price": stmt.excluded.avg_price,
                    "volume": stmt.excluded.volume,
                    "fetched_at": stmt.excluded.fetched_at
                },
            )
            await self._session.execute(stmt)
            
        await self._session.commit()
        
    async def _update_meta_success(
        self, meta: CacheMetadata, provider: str
    ) -> None:
        await self._session.execute(
            update(CacheMetadata)
            .where(CacheMetadata.id == meta.id)
            .values(
                last_fetched=datetime.now(timezone.utc),
                is_stale=False,
                fetch_count=CacheMetadata.fetch_count + 1,
                error_count = 0,
                provider_used=provider, 
                updated_at=datetime.now(timezone.utc)
            )
        )
        await self._session.commit()
        
        
    async def _update_meta_error(self, meta: CacheMetadata) -> None:
        await self._session.execute(
            update(CacheMetadata)
            .where(CacheMetadata.id == meta.id)
            .values(
                error_count=CacheMetadata.error_count + 1,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self._session.commit()
        
        
        
    @staticmethod
    def _age_hours(last_fetched: datetime | None) -> float:
        if last_fetched is None:
            return float("inf")
        if last_fetched.tzinfo is None:
            last_fetched = last_fetched.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - last_fetched
        return delta.total_seconds() / 3600
    
    @staticmethod
    def _period_to_cutoff(period: str):
        from datetime import date, timedelta
        
        today = date.today()
        mapping = {
            "1W" : timedelta(weeks=1),
            "1M" : timedelta(days=30),
            "3M" : timedelta(days=90),
            "6M" : timedelta(days=180),
            "1Y" : timedelta(days=365),
            "3Y" : timedelta(days=365 * 3),
            "5Y" : timedelta(days=365 * 5), 
        }
        delta = mapping.get(period, timedelta(days=365))
        return today - delta
    
           