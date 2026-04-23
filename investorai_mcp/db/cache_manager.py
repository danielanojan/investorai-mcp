import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic, TypeVar

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession


def _get_insert(engine_url: str):
    if "postgresql" in engine_url:
        return pg_insert
    return sqlite_insert


from investorai_mcp.data.base import DataProviderAdapter, OHLCVRecord
from investorai_mcp.db.models import CacheMetadata, PriceHistory, Ticker

logger = logging.getLogger(__name__)

# Per-symbol locks — prevent duplicate refreshes for the same ticker.
# setdefault is used instead of if-not-in/assign to prevent a race where two
# coroutines both pass the membership check before either inserts a lock.
# Two coroutines can both evaluate asyncio.Lock() as the default argument, but
# dict.setdefault is atomic in CPython — only the first caller's lock is stored,
# and both callers receive the same lock object back. No separate locks are created.
_refresh_locks: dict[str, asyncio.Lock] = {}


def _refresh_lock(symbol: str) -> asyncio.Lock:
    return _refresh_locks.setdefault(symbol, asyncio.Lock())


# Global write lock — SQLite has one file-level write lock regardless of symbol.
# When 50 tickers refresh concurrently (e.g. agent loop broad query), all try to
# write the same file. This serialises writes at the Python level before they
# reach SQLite, avoiding "database is locked" errors.
_global_write_lock = asyncio.Lock()

T = TypeVar("T")

TTL_SECONDS = {
    "price_history": 86400,  # 24 hours
    "news": 14400,  # 4 hours
    "ticker_info": 604800,  # 7 days
    "sentiment": 14400,  # 4 hours
}


# A generic wrapper around any returned data. Generic[T] means it can wrap any type — CacheResult[list[PriceHistory]], CacheResult[list[NewsRecord]], etc.
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

    async def get_prices(self, symbol: str, period: str = "1Y") -> CacheResult[list[PriceHistory]]:
        # This is the main method users of this class call. It implements a stale-while-revalidate caching strategy:
        meta = await self._get_or_create_meta(symbol, "price_history")

        age_hours = self._age_hours(meta.last_fetched)
        is_fresh = not meta.is_stale and age_hours < (TTL_SECONDS["price_history"] / 3600)

        # First it gets the cache metadata record for this symbol. Then it calculates how old the data is and whether it's still within the TTL window.
        if is_fresh:
            # If fresh — read from DB and return immediately. No network call needed.
            rows = await self._read_prices(symbol, period)
            return CacheResult(
                data=rows,
                is_stale=False,
                data_age_hours=age_hours,
                provider_used=meta.provider_used,
            )

        # If stale — this is the clever part. It returns the old data immediately so the user isn't waiting, then kicks off a background refresh task.
        # The next request will get fresh data. This is the classic stale-while-revalidate pattern — prioritise speed over freshness.
        rows = await self._read_prices(symbol, period)
        lock = _refresh_lock(symbol)
        if not lock.locked():
            task = asyncio.create_task(self._locked_refresh_prices(symbol, meta, lock))
            task.add_done_callback(
                lambda t: logger.error(
                    "Background price refresh failed for %s: %s", symbol, t.exception()
                )
                if t.exception()
                else None
            )
        return CacheResult(
            data=rows, is_stale=True, data_age_hours=age_hours, provider_used=meta.provider_used
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
            data=rows, is_stale=False, data_age_hours=0.0, provider_used=meta.provider_used
        )

    async def ensure_ticker_exists(self, symbol: str) -> Ticker | None:
        from investorai_mcp.stocks import get_ticker_info

        info = get_ticker_info(symbol)
        if not info:
            return None  # not in our supported list

        from investorai_mcp.db import database_url

        insert = _get_insert(database_url)

        stmt = (
            insert(Ticker)
            .values(
                symbol=symbol,
                name=info["name"],
                sector=info["sector"],
                exchange=info["exchange"],
                is_supported=True,
            )
            .on_conflict_do_nothing(index_elements=["symbol"])
        )
        await self._session.execute(stmt)
        await self._session.commit()
        return await self._session.get(Ticker, symbol)

    ######## Private : meta -----------------------------
    async def _get_or_create_meta(self, symbol: str, data_type: str) -> CacheMetadata:
        from investorai_mcp.db import database_url

        insert = _get_insert(database_url)

        # Upsert — on_conflict_do_nothing prevents duplicate rows under concurrent requests.
        # UniqueConstraint("symbol", "data_type") already exists on the table.
        stmt = (
            insert(CacheMetadata)
            .values(
                symbol=symbol,
                data_type=data_type,
                ttl_seconds=TTL_SECONDS[data_type],
                is_stale=True,
                fetch_count=0,
                error_count=0,
            )
            .on_conflict_do_nothing(index_elements=["symbol", "data_type"])
        )
        await self._session.execute(stmt)
        await self._session.commit()

        result = await self._session.execute(
            select(CacheMetadata).where(
                CacheMetadata.symbol == symbol,
                CacheMetadata.data_type == data_type,
            )
        )
        meta = result.scalar_one()
        result.close()
        return meta

    ############# Private: read --------------------------
    async def _read_prices(self, symbol: str, period: str) -> list[PriceHistory]:
        cutoff = self._period_to_cutoff(period)
        stmt = (
            select(PriceHistory)
            .where(
                PriceHistory.symbol == symbol,
                PriceHistory.date >= cutoff,
            )
            .order_by(PriceHistory.date.asc())
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        result.close()
        return rows

    async def get_prices_multi(
        self, symbols: list[str], period: str = "1Y"
    ) -> dict[str, list[PriceHistory]]:
        """Batch read prices for multiple symbols in a single query."""
        if not symbols:
            return {}
        cutoff = self._period_to_cutoff(period)
        stmt = (
            select(PriceHistory)
            .where(
                PriceHistory.symbol.in_(symbols),
                PriceHistory.date >= cutoff,
            )
            .order_by(PriceHistory.symbol.asc(), PriceHistory.date.asc())
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        result.close()
        grouped: dict[str, list[PriceHistory]] = {}
        for row in rows:
            grouped.setdefault(row.symbol, []).append(row)
        return grouped

    async def get_stale_or_missing(self, symbols: list[str], data_type: str) -> list[str]:
        """Return symbols whose cache is stale or has never been fetched."""
        if not symbols:
            return []
        stmt = select(CacheMetadata).where(
            CacheMetadata.symbol.in_(symbols),
            CacheMetadata.data_type == data_type,
        )
        result = await self._session.execute(stmt)
        existing = {m.symbol: m for m in result.scalars().all()}
        ttl_hours = TTL_SECONDS[data_type] / 3600
        needs: list[str] = []
        for symbol in symbols:
            meta = existing.get(symbol)
            if meta is None:
                needs.append(symbol)
            elif meta.is_stale or self._age_hours(meta.last_fetched) >= ttl_hours:
                needs.append(symbol)
        return needs

    @classmethod
    async def refresh_prices_standalone(cls, symbol: str, adapter: "DataProviderAdapter") -> None:
        """Refresh one symbol's prices in its own session. Safe for asyncio.gather calls."""
        from investorai_mcp.db import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            manager = cls(session, adapter)
            meta = await manager._get_or_create_meta(symbol, "price_history")
            lock = _refresh_lock(symbol)
            async with lock:
                async with _global_write_lock:
                    try:
                        await asyncio.wait_for(manager._refresh_prices(symbol, meta), timeout=60)
                    except TimeoutError:
                        logger.error("Refresh timed out for %s after 60s", symbol)

    ####### Private : refresh --------------------------
    async def _locked_refresh_prices(
        self, symbol: str, meta: CacheMetadata, lock: asyncio.Lock
    ) -> None:
        async with lock:  # per-symbol: skip if already refreshing this ticker
            async with _global_write_lock:  # global: serialise all SQLite writes
                try:
                    await asyncio.wait_for(self._refresh_prices(symbol, meta), timeout=30)
                except TimeoutError:
                    logger.error("Price refresh timed out for %s after 30s", symbol)

    async def _refresh_prices(self, symbol: str, meta: CacheMetadata) -> None:
        logger.info("Refreshing price history for %s", symbol)
        try:
            records: list[OHLCVRecord] = await self._adapter.fetch_ohlcv(symbol, period="5y")
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

    async def _upsert_prices(self, symbol: str, records: list[OHLCVRecord]) -> None:
        from investorai_mcp.config import settings

        insert = _get_insert(settings.database_url)

        for record in records:
            stmt = insert(PriceHistory).values(
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
                fetched_at=datetime.now(UTC),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "date"],
                set_={
                    "adj_close": stmt.excluded.adj_close,
                    "avg_price": stmt.excluded.avg_price,
                    "volume": stmt.excluded.volume,
                    "fetched_at": stmt.excluded.fetched_at,
                },
            )
            await self._session.execute(stmt)

        await self._session.commit()

    async def _update_meta_success(self, meta: CacheMetadata, provider: str) -> None:
        await self._session.execute(
            update(CacheMetadata)
            .where(CacheMetadata.id == meta.id)
            .values(
                last_fetched=datetime.now(UTC),
                is_stale=False,
                fetch_count=CacheMetadata.fetch_count + 1,
                error_count=0,
                provider_used=provider,
                updated_at=datetime.now(UTC),
            )
        )
        await self._session.commit()

    async def _update_meta_error(self, meta: CacheMetadata) -> None:
        await self._session.execute(
            update(CacheMetadata)
            .where(CacheMetadata.id == meta.id)
            .values(
                error_count=CacheMetadata.error_count + 1,
                updated_at=datetime.now(UTC),
            )
        )
        await self._session.commit()

    @staticmethod
    def _age_hours(last_fetched: datetime | None) -> float:
        if last_fetched is None:
            return float("inf")
        if last_fetched.tzinfo is None:
            last_fetched = last_fetched.replace(tzinfo=UTC)
        delta = datetime.now(UTC) - last_fetched
        return delta.total_seconds() / 3600

    @staticmethod
    def _period_to_cutoff(period: str):
        from datetime import date, timedelta

        today = date.today()
        mapping = {
            "1W": timedelta(weeks=1),
            "1M": timedelta(days=30),
            "3M": timedelta(days=90),
            "6M": timedelta(days=180),
            "1Y": timedelta(days=365),
            "3Y": timedelta(days=365 * 3),
            "5Y": timedelta(days=365 * 5),
        }
        delta = mapping.get(period, timedelta(days=365))
        return today - delta
