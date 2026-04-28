"""
Pre population script - loads 5 yrs of price history for 50 stocks

Run this ONCE before launch so day-one users always have a warm cache

Usage:
    python scripts/populate.py                  #full run on all 50 tickers
    python scripts/populate.py --ticker AAPL      #only populate for AAPL
    python scripts/populate.py --dry-run          #run without writing to DB, just to see output and check for errors
"""

import argparse
import asyncio
import logging
import sys
import time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from investorai_mcp.data.yfinance_adapter import YFinanceAdapter

# allow running from project root
sys.path.insert(0, ".")

from investorai_mcp.config import settings
from investorai_mcp.db.cache_manager import CacheManager
from investorai_mcp.stocks import SUPPORTED_TICKERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)-7s - %(message)s",
    datefmt="%H:%M:%S",
)

log = logging.getLogger("populate")

RATE_LIMIT_SLEEP = 0.5  # seconds between yfinance calls


async def populate_ticker(
    symbol: str,
    session: AsyncSession,
    adapter: YFinanceAdapter,
    dry_run: bool,
) -> tuple[int, int]:
    """
    Fetch and store 5 yrs of OHLCV data for one ticker
    Returns (success, record_count)
    """

    manager = CacheManager(session, adapter)

    # ensure the ticker row exists
    ticker = await manager.ensure_ticker_exists(symbol)
    if ticker is None:
        log.error("%s ticker not found in SUPPORTED_TICKERS. Skipping.", symbol)
        return False, 0

    if dry_run:
        log.info("%s [DRY RUN] Would fetch 5 yrs of OHLCV data", symbol)
        return True, 0

    try:
        records = await adapter.fetch_ohlcv(symbol, "5y")
        if not records:
            log.warning("%s No records returned from yfinance", symbol)
            return False, 0

        await manager._upsert_prices(symbol, records)

        # Mark cache as fresh
        meta = await manager._get_or_create_meta(symbol, "price_history")
        await manager._update_meta_success(meta, provider="yfinance")

        log.info("%s %d records loaded", symbol, len(records))
        return True, len(records)

    except Exception as e:
        log.error("%s Error fetching/storing data: %s", symbol, e)
        return False, 0


async def main(dry_run: bool, single_ticker: str | None) -> None:
    log.info("InvestorAI pre-production script")
    log.info("Database %s", settings.database_url)
    log.info("Dry run: %s", dry_run)

    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    adapter = YFinanceAdapter()

    tickers = [single_ticker] if single_ticker else list(SUPPORTED_TICKERS.keys())
    total = len(tickers)
    suceeded = 0
    total_records = 0
    failed = 0

    log.info("Loading %d tickers", total)
    start = time.time()

    for i, symbol in enumerate(tickers, 1):
        log.info("Processing [%d/%d]: %s", i, total, symbol)
        async with Session() as session:
            ok, count = await populate_ticker(symbol, session, adapter, dry_run)

            if ok:
                suceeded += 1
                total_records += count
            else:
                failed += 1
        # rate limit - -avoid hitting yfinance too hard in case of large ticker list. In a real production script, you might want a more sophisticated rate limiting strategy that adapts to the number of tickers and API response times.

        if i < total:
            await asyncio.sleep(RATE_LIMIT_SLEEP)

    elapsed = time.time() - start
    log.info("-" * 50)
    log.info("complete in %.1f seconds", elapsed)
    log.info("Success: %d/%d tickers", suceeded, total)
    if failed:
        log.warning("Failed : %d tickers", failed)
    if not dry_run:
        log.info("Records: %d total price history rows", total_records)

    await engine.dispose()

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pre-populate the database with price history data"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Run without writing to the database"
    )
    parser.add_argument(
        "--ticker", type=str, default=None, help="Only populate data for this ticker symbol"
    )
    args = parser.parse_args()

    if args.ticker and args.ticker.upper() not in SUPPORTED_TICKERS:
        print(f"Error: Ticker '{args.ticker}' is not in the supported tickers list.")
        sys.exit(1)

    asyncio.run(
        main(dry_run=args.dry_run, single_ticker=args.ticker.upper() if args.ticker else None)
    )
