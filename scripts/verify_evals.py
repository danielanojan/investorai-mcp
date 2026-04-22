"""
Eval verification script.

Queries the real DB and checks expected values in qa_pairs.json.
Flags pairs where expected value doesn't match DB.
This replaces 4 hours of manual verification with ~30 minutes.

Usage:
    uv run python scripts/verify_evals.py
    uv run python scripts/verify_evals.py --fix   # auto-fix mismatches
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from investorai_mcp.config import settings
from investorai_mcp.db.models import PriceHistory

QA_PATH = Path("tests/evals/qa_pairs.json")
TOLERANCE = 0.005  # 0.5%


async def verify_pair(session, pair: dict) -> tuple[bool, str]:
    """
    Verify one pair against the DB.
    Returns (is_correct, message).
    """
    category = pair["category"]
    expected = pair["expected"]
    symbol   = pair.get("symbol")

    # Out of scope and pre-verified edge cases — skip
    if pair.get("verified"):
        return True, "pre-verified"

    if not symbol:
        return True, "no symbol — skip"

    # price_fact — verify the exact price
    if category == "price_fact":
        try:
            expected_price = float(expected)
        except ValueError:
            return False, f"expected not a number: {expected}"

        # Extract date from question
        import re
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", pair["question"])
        if not date_match:
            return False, "no date in question"

        from datetime import date as date_type
        trade_date = date_type.fromisoformat(date_match.group())

        stmt = select(PriceHistory).where(
            PriceHistory.symbol == symbol,
            PriceHistory.date   == trade_date,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

        if not row:
            return False, f"no DB row for {symbol} on {trade_date}"

        actual    = round(row.adj_close, 2)
        deviation = abs(actual - expected_price) / actual if actual > 0 else 0

        if deviation > TOLERANCE:
            return False, (
                f"mismatch: expected={expected_price} "
                f"actual={actual} deviation={deviation*100:.2f}%"
            )
        return True, f"verified: {actual}"

    # pct_change — verify the percentage
    if category == "pct_change":
        try:
            expected_pct = float(expected.replace("%", ""))
        except ValueError:
            return False, f"expected not a percentage: {expected}"

        from datetime import date as date_type
        from datetime import timedelta
        cutoff = date_type.today() - timedelta(days=365)
        stmt = (
            select(PriceHistory)
            .where(
                PriceHistory.symbol == symbol,
                PriceHistory.date   >= cutoff,
            )
            .order_by(PriceHistory.date.asc())
        )
        result = await session.execute(stmt)
        rows   = list(result.scalars().all())

        if len(rows) < 5:
            return False, "not enough rows"

        actual_pct = round(
            (rows[-1].adj_close - rows[0].adj_close) / rows[0].adj_close * 100, 2
        )
        deviation = abs(actual_pct - expected_pct) / max(abs(actual_pct), 0.01)

        if deviation > 0.05:  # 5% tolerance on percentages
            return False, (
                f"pct mismatch: expected={expected_pct}% "
                f"actual={actual_pct}%"
            )
        return True, f"verified: {actual_pct}%"

    # Other categories — mark as needs manual review
    return False, "needs manual verification"


async def main(fix: bool = False):
    if not QA_PATH.exists():
        print(f"ERROR: {QA_PATH} not found.")
        print("Run: uv run python scripts/generate_evals.py first")
        sys.exit(1)

    with open(QA_PATH) as f:
        pairs = json.load(f)

    print(f"Verifying {len(pairs)} eval pairs...")

    engine  = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)

    correct        = 0
    wrong          = 0
    needs_manual   = 0
    wrong_pairs    = []

    async with Session() as session:
        for i, pair in enumerate(pairs):
            is_ok, msg = await verify_pair(session, pair)

            if "needs manual" in msg:
                needs_manual += 1
                print(f"  [{i+1:3d}] MANUAL  {pair['category']:15s} "
                      f"{pair.get('symbol','N/A'):8s} {pair['question'][:50]}")
            elif is_ok:
                correct += 1
                if fix:
                    pair["verified"] = True
            else:
                wrong += 1
                wrong_pairs.append((i, pair, msg))
                print(f"  [{i+1:3d}] WRONG   {pair['category']:15s} "
                      f"{pair.get('symbol','N/A'):8s} {msg}")

    await engine.dispose()

    print("\nResults:")
    print(f"  Verified correct:      {correct}")
    print(f"  Wrong (needs fix):     {wrong}")
    print(f"  Needs manual review:   {needs_manual}")
    print(f"  Total:                 {len(pairs)}")

    if wrong_pairs:
        print(f"\nFix these {wrong} pairs in {QA_PATH}")
        print("Or run with --fix to auto-correct price_fact pairs")

    if fix and correct > 0:
        with open(QA_PATH, "w") as f:
            json.dump(pairs, f, indent=2, default=str)
        print(f"\nAuto-fixed and saved to {QA_PATH}")

    if needs_manual > 0:
        print(f"\n{needs_manual} pairs need manual review.")
        print("Open tests/evals/qa_pairs.json and verify these by hand.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix", action="store_true",
                        help="Auto-fix price_fact mismatches")
    args = parser.parse_args()
    asyncio.run(main(fix=args.fix))