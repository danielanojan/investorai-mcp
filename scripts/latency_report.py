"""
Latency playground for developers.

Usage:
    uv run python scripts/latency_report.py
    uv run python scripts/latency_report.py --limit 20
    uv run python scripts/latency_report.py --since 7d
"""

import argparse
import asyncio
import math
import sys
from datetime import UTC, datetime, timedelta


def _percentile(sorted_values: list[int], p: float) -> int:
    if not sorted_values:
        return 0
    idx = math.ceil(len(sorted_values) * p / 100) - 1
    return sorted_values[max(0, min(idx, len(sorted_values) - 1))]


def _bar(value: int, max_value: int, width: int = 30) -> str:
    filled = round(width * value / max_value) if max_value else 0
    return "█" * filled + "░" * (width - filled)


async def report(since_days: int, limit: int) -> None:
    from sqlalchemy import select

    from investorai_mcp.db import AsyncSessionLocal
    from investorai_mcp.db.models import ChatRequestLog

    cutoff = datetime.now(UTC) - timedelta(days=since_days)

    async with AsyncSessionLocal() as session:
        rows = (
            (
                await session.execute(
                    select(ChatRequestLog)
                    .where(ChatRequestLog.ts >= cutoff)
                    .order_by(ChatRequestLog.ts.asc())
                )
            )
            .scalars()
            .all()
        )

    if not rows:
        print(f"No chat calls recorded in the last {since_days} days.")
        return

    success = [r for r in rows if r.status == "success"]
    errors = [r for r in rows if r.status == "error"]
    lats = sorted(r.total_latency_ms for r in success)

    p50 = _percentile(lats, 50)
    p95 = _percentile(lats, 95)
    p99 = _percentile(lats, 99)
    avg = round(sum(lats) / len(lats)) if lats else 0
    max_lat = lats[-1] if lats else 0

    # ── Summary ───────────────────────────────────────────────────────────
    print()
    print("═" * 60)
    print("  InvestorAI — Chat Latency Report")
    print(f"  Period : last {since_days} day(s)")
    print(f"  Window : {rows[0].ts:%Y-%m-%d %H:%M} → {rows[-1].ts:%Y-%m-%d %H:%M} UTC")
    print("═" * 60)
    print(f"  Total calls   : {len(rows)}  ({len(success)} success / {len(errors)} error)")
    print(f"  Average       : {avg:>6} ms")
    print(f"  P50           : {p50:>6} ms")
    print(f"  P95           : {p95:>6} ms  ← threshold")
    print(f"  P99           : {p99:>6} ms")
    print(f"  Max           : {max_lat:>6} ms")
    print()

    # ── Latency histogram (10 buckets) ────────────────────────────────────
    if lats:
        bucket_ms = max(1, max_lat // 10)
        buckets: dict[int, int] = {}
        for v in lats:
            b = (v // bucket_ms) * bucket_ms
            buckets[b] = buckets.get(b, 0) + 1

        print("  Latency distribution:")
        max_count = max(buckets.values())
        for lower in sorted(buckets):
            count = buckets[lower]
            marker = " ← P95" if lower <= p95 < lower + bucket_ms else ""
            print(
                f"  {lower:>6}-{lower + bucket_ms:<6}ms  "
                f"{_bar(count, max_count, 25)}  {count:>3}{marker}"
            )
        print()

    # ── Outliers (> P95) ──────────────────────────────────────────────────
    outliers = sorted(
        [r for r in success if r.total_latency_ms > p95],
        key=lambda r: r.total_latency_ms,
        reverse=True,
    )

    print(f"  Outliers exceeding P95 ({p95} ms): {len(outliers)} call(s)")
    if not outliers:
        print("  ✓ No outliers — all calls within P95.")
    else:
        print()
        print(f"  {'Latency':>8}  {'Excess':>7}  {'Symbols':<10}  Question")
        print("  " + "-" * 72)
        for r in outliers[:limit]:
            excess = r.total_latency_ms - p95
            question = r.question[:55] + "…" if len(r.question) > 55 else r.question
            print(f"  {r.total_latency_ms:>6} ms  +{excess:>5} ms  {r.symbols:<10}  {question}")
        if len(outliers) > limit:
            print(f"\n  … {len(outliers) - limit} more (increase --limit to see all)")
    print()
    print("═" * 60)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="InvestorAI latency playground")
    parser.add_argument(
        "--since", default="30d", help="Look-back window e.g. 7d, 30d (default: 30d)"
    )
    parser.add_argument(
        "--limit", type=int, default=20, help="Max outlier rows to display (default: 20)"
    )
    args = parser.parse_args()

    since_str = args.since.lower().rstrip("d")
    try:
        since_days = int(since_str)
    except ValueError:
        print(f"Invalid --since value: {args.since}. Use e.g. 7d or 30d.")
        sys.exit(1)

    asyncio.run(report(since_days=since_days, limit=args.limit))


if __name__ == "__main__":
    main()
