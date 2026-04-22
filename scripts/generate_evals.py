"""
Eval pair generator.

Queries the real DB and generates Q&A pairs with correct
expected values. Run this once after prepopulate.py.

Usage:
    uv run python scripts/generate_evals.py
    uv run python scripts/generate_evals.py --count 200
"""
import asyncio
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, ".")

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from investorai_mcp.config import settings
from investorai_mcp.db.models import PriceHistory
from investorai_mcp.stocks import SUPPORTED_TICKERS

OUTPUT_PATH = Path("tests/evals/qa_pairs.json")


async def get_random_price(session, symbol: str) -> tuple[date, float] | None:
    """Get a random price row for a symbol."""
    stmt = (
        select(PriceHistory)
        .where(PriceHistory.symbol == symbol)
        .order_by(func.random())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row:
        return row.date, round(row.adj_close, 2)
    return None


async def get_period_stats(
    session, symbol: str, days: int
) -> dict | None:
    """Get start/end/high/low for a period."""
    cutoff = date.today() - timedelta(days=days)
    stmt = (
        select(PriceHistory)
        .where(
            PriceHistory.symbol == symbol,
            PriceHistory.date >= cutoff,
        )
        .order_by(PriceHistory.date.asc())
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    if len(rows) < 5:
        return None

    adj_closes = [r.adj_close for r in rows]
    start = round(adj_closes[0], 2)
    end   = round(adj_closes[-1], 2)
    high  = round(max(adj_closes), 2)
    low   = round(min(adj_closes), 2)
    ret   = round((end - start) / start * 100, 2)

    return {
        "start":      start,
        "end":        end,
        "high":       high,
        "low":        low,
        "return_pct": ret,
        "start_date": rows[0].date.isoformat(),
        "end_date":   rows[-1].date.isoformat(),
        "days":       len(rows),
    }


async def generate_pairs(count: int = 200) -> list[dict]:
    engine  = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)

    symbols = list(SUPPORTED_TICKERS.keys())
    pairs   = []

    async with Session() as session:

        # ── Category 1: price_fact (30%) ─────────────────────────────────
        target = int(count * 0.30)
        attempts = 0
        while len([p for p in pairs if p["category"] == "price_fact"]) < target:
            if attempts > target * 5:
                break
            attempts += 1
            symbol = random.choice(symbols)  # noqa: S311
            result = await get_random_price(session, symbol)
            if not result:
                continue
            trade_date, price = result
            name = SUPPORTED_TICKERS[symbol]["name"]
            pairs.append({
                "category": "price_fact",
                "question": (
                    f"What was {name} ({symbol}) adjusted close price "
                    f"on {trade_date}?"
                ),
                "expected":  str(price),
                "symbol":    symbol,
                "verified":  False,
            })

        # ── Category 2: trend (20%) ───────────────────────────────────────
        target = int(count * 0.20)
        for period_days, label in [(365, "1Y"), (180, "6M"), (90, "3M")]:
            for symbol in random.sample(symbols, min(10, len(symbols))):
                if len([p for p in pairs if p["category"] == "trend"]) >= target:
                    break
                stats = await get_period_stats(session, symbol, period_days)
                if not stats:
                    continue
                name = SUPPORTED_TICKERS[symbol]["name"]
                direction = "gained" if stats["return_pct"] >= 0 else "lost"
                pairs.append({
                    "category": "trend",
                    "question": (
                        f"How has {name} ({symbol}) performed "
                        f"over the last {label}?"
                    ),
                    "expected": (
                        f"{symbol} {direction} "
                        f"{abs(stats['return_pct'])}% over {label}, "
                        f"from ${stats['start']} to ${stats['end']}."
                    ),
                    "symbol":   symbol,
                    "verified": False,
                })

        # ── Category 3: pct_change (15%) ──────────────────────────────────
        target = int(count * 0.15)
        for symbol in random.sample(symbols, min(20, len(symbols))):
            if len([p for p in pairs if p["category"] == "pct_change"]) >= target:
                break
            stats = await get_period_stats(session, symbol, 365)
            if not stats:
                continue
            name = SUPPORTED_TICKERS[symbol]["name"]
            pairs.append({
                "category": "pct_change",
                "question": (
                    f"What is the percentage change in {name} ({symbol}) "
                    f"over the past year?"
                ),
                "expected": f"{stats['return_pct']}%",
                "symbol":   symbol,
                "verified": False,
            })

        # ── Category 4: high_low (10%) ────────────────────────────────────
        target = int(count * 0.10)
        for symbol in random.sample(symbols, min(15, len(symbols))):
            if len([p for p in pairs if p["category"] == "high_low"]) >= target:
                break
            stats = await get_period_stats(session, symbol, 365)
            if not stats:
                continue
            name = SUPPORTED_TICKERS[symbol]["name"]
            pairs.append({
                "category": "high_low",
                "question": (
                    f"What was {name} ({symbol})'s 52-week high and low?"
                ),
                "expected": (
                    f"52-week high: ${stats['high']}, "
                    f"52-week low: ${stats['low']}"
                ),
                "symbol":   symbol,
                "verified": False,
            })

        # ── Category 5: out_of_scope (10%) ────────────────────────────────
        out_of_scope = [
            {"category":"out_of_scope","question":"What is Bitcoin's current price?","expected":"not_supported","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"Should I buy Tesla stock right now?","expected":"no_financial_advice","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"What is the price of gold?","expected":"not_supported","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"Give me options trading strategies for AAPL","expected":"no_financial_advice","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"What stocks should I buy for retirement?","expected":"no_financial_advice","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"What is Ethereum worth today?","expected":"not_supported","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"Should I sell my NVDA shares?","expected":"no_financial_advice","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"What is the S&P 500 index value?","expected":"not_supported","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"Is AAPL a good investment?","expected":"no_financial_advice","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"What will TSLA stock price be next year?","expected":"no_financial_advice","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"What is the price of crude oil?","expected":"not_supported","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"Should I invest in index funds or individual stocks?","expected":"no_financial_advice","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"What is DOGECOIN trading at?","expected":"not_supported","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"Give me a buy signal for MSFT","expected":"no_financial_advice","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"What is the best stock to buy right now?","expected":"no_financial_advice","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"What is Apple's bond rating?","expected":"not_supported","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"Should I put money in AAPL or a savings account?","expected":"no_financial_advice","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"What is the VIX index today?","expected":"not_supported","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"Tell me AAPL options chain","expected":"not_supported","symbol":None,"verified":True},
            {"category":"out_of_scope","question":"What is the Fed interest rate?","expected":"not_supported","symbol":None,"verified":True},
        ]
        target = int(count * 0.10)
        pairs.extend(out_of_scope[:target])

        # ── Category 6: edge_case (10%) ───────────────────────────────────
        edge_cases = [
            {"category":"edge_case","question":"Show me BRK-B price history","expected":"supported","symbol":"BRK-B","verified":True},
            {"category":"edge_case","question":"What was AAPL price on a Saturday?","expected":"no_trading_on_weekends","symbol":"AAPL","verified":True},
            {"category":"edge_case","question":"Show me DOGECOIN prices","expected":"not_supported","symbol":None,"verified":True},
            {"category":"edge_case","question":"Get price history for brk-b","expected":"supported","symbol":"BRK-B","verified":True},
            {"category":"edge_case","question":"Show me prices for aapl","expected":"supported","symbol":"AAPL","verified":True},
            {"category":"edge_case","question":"What is the price of XYZ123?","expected":"not_supported","symbol":None,"verified":True},
            {"category":"edge_case","question":"Show me AAPL data for the next year","expected":"supported","symbol":"AAPL","verified":True},
            {"category":"edge_case","question":"Get prices for BTC-USD","expected":"not_supported","symbol":None,"verified":True},
            {"category":"edge_case","question":"Show me TSLA data for 10 years","expected":"supported","symbol":"TSLA","verified":True},
            {"category":"edge_case","question":"What was MSFT price on Christmas 2025?","expected":"no_trading_on_weekends","symbol":"MSFT","verified":True},
            {"category":"edge_case","question":"Show me SPY ETF prices","expected":"not_supported","symbol":None,"verified":True},
            {"category":"edge_case","question":"Get NVDA data for 1 week","expected":"supported","symbol":"NVDA","verified":True},
            {"category":"edge_case","question":"What is the price of AMZN on New Year 2026?","expected":"no_trading_on_weekends","symbol":"AMZN","verified":True},
            {"category":"edge_case","question":"Show me GOOGL prices since IPO","expected":"supported","symbol":"GOOGL","verified":True},
            {"category":"edge_case","question":"Get prices for META on a Sunday","expected":"no_trading_on_weekends","symbol":"META","verified":True},
            {"category":"edge_case","question":"Show me prices for FAKE_TICKER","expected":"not_supported","symbol":None,"verified":True},
            {"category":"edge_case","question":"Get JPM data for 5 years","expected":"supported","symbol":"JPM","verified":True},
            {"category":"edge_case","question":"What is the price of VOO ETF?","expected":"not_supported","symbol":None,"verified":True},
            {"category":"edge_case","question":"Show me WMT prices","expected":"supported","symbol":"WMT","verified":True},
            {"category":"edge_case","question":"Get prices for QQQ","expected":"not_supported","symbol":None,"verified":True},
        ]
        target = int(count * 0.10)
        pairs.extend(edge_cases[:target])

        # ── Category 7: comparison (5%) ───────────────────────────────────
        symbol_pairs = [
            ("AAPL","MSFT"), ("NVDA","AMD"), ("JPM","BAC"),
            ("TSLA","AMZN"), ("META","GOOGL"), ("V","MA"),
            ("PFE","JNJ"), ("XOM","CVX"), ("WMT","COST"),
            ("NFLX","DIS"),
        ]
        target = int(count * 0.05)
        for s1, s2 in symbol_pairs:
            if len([p for p in pairs if p["category"] == "comparison"]) >= target:
                break
            stats1 = await get_period_stats(session, s1, 365)
            stats2 = await get_period_stats(session, s2, 365)
            if not stats1 or not stats2:
                continue
            winner = s1 if stats1["return_pct"] > stats2["return_pct"] else s2
            pairs.append({
                "category": "comparison",
                "question": f"Which performed better over the last year: {s1} or {s2}?",
                "expected": winner,
                "symbol":   None,
                "verified": False,
            })

    await engine.dispose()

    # Shuffle and trim to requested count
    random.shuffle(pairs)
    return pairs[:count]


async def main(count: int = 200):
    print(f"Generating {count} eval pairs from DB...")
    pairs = await generate_pairs(count)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(pairs, f, indent=2, default=str)

    categories = {}
    for p in pairs:
        categories[p["category"]] = categories.get(p["category"], 0) + 1

    print(f"\nGenerated {len(pairs)} pairs:")
    for cat, cnt in sorted(categories.items()):
        verified = sum(1 for p in pairs
                      if p["category"] == cat and p["verified"])
        print(f"  {cat:20s} {cnt:3d} pairs  "
              f"({verified} pre-verified)")

    unverified = sum(1 for p in pairs if not p["verified"])
    print(f"\nPairs needing manual verification: {unverified}")
    print(f"Output: {OUTPUT_PATH}")
    print("\nNext step: uv run python scripts/verify_evals.py")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=200)
    args = parser.parse_args()
    asyncio.run(main(args.count))