"""
Post-generation validator.

Extracts every financial number from LLM responses and
verifies each against the database within tolerance.
Suppresses response only when numbers are provably wrong.

Design principles:
- Honest "I don't have data" responses pass through unchanged
- Only block responses with fabricated numbers
- 2% tolerance to allow for rounding differences
- Skip very large numbers (market caps) that can't be verified
"""

import logging
import re
from dataclasses import dataclass, field

from investorai_mcp.llm.prompt_builder import PriceSummaryStats

logger = logging.getLogger(__name__)

TOLERANCE_PCT = 0.02  # 2% tolerance

IDK_RESPONSE = (
    "I don't have reliable data to answer this accurately. "
    "Please check a financial data source directly for precise figures."
)

# ── Number extraction patterns ────────────────────────────────────────────

_PATTERNS = [
    re.compile(r"\$([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)"),
    re.compile(r"[+-]?([0-9]+(?:\.[0-9]+)?)\s*%"),
    re.compile(r"\b([0-9]{1,4}\.[0-9]{2,})\b"),
]

_EXCLUDE_PATTERNS = [
    re.compile(r"^20[0-9]{2}$"),
    re.compile(r"^[0-9]$"),
    re.compile(r"^[0-9]{2}$"),
]


# ── Data classes ──────────────────────────────────────────────────────────


@dataclass
class Violation:
    claimed: float
    actual: float
    deviation: float


@dataclass
class ValidationResult:
    passed: bool
    violations: list[Violation] = field(default_factory=list)
    response: str = ""


# ── Number extraction ─────────────────────────────────────────────────────


def extract_numbers(text: str) -> list[float]:
    """
    Extract financial numbers from response text.
    Handles: $174.32, 12.3%, 174.32
    Excludes: years, single/double digits, values over 100,000
    """
    numbers = set()

    for pattern in _PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(1).replace(",", "")
            try:
                value = float(raw)

                if any(p.match(str(int(value))) for p in _EXCLUDE_PATTERNS if value == int(value)):
                    continue

                if value < 0.01:
                    continue

                if value > 100_000:
                    continue

                numbers.add(round(value, 4))

            except (ValueError, OverflowError):
                continue

    return sorted(numbers)


def _get_ground_truths(stats: PriceSummaryStats) -> list[float]:
    return [
        stats.start_price,
        stats.end_price,
        stats.high_price,
        stats.low_price,
        stats.avg_price,
        abs(stats.period_return_pct),
        stats.volatility_pct,
        float(stats.trading_days),
    ]


def _find_nearest(value: float, ground_truths: list[float]) -> float | None:
    if not ground_truths:
        return None
    positives = [gt for gt in ground_truths if gt > 0]
    if not positives:
        return None
    candidates = [gt for gt in positives if abs(gt - value) / max(gt, value) < 0.5]
    # If nothing is within 50%, fall back to absolute nearest so the
    # deviation check still runs — prevents hallucinated values from
    # being silently skipped.
    pool = candidates if candidates else positives
    return min(pool, key=lambda gt: abs(gt - value))


# ── Validator ─────────────────────────────────────────────────────────────


def validate_response(
    response_text: str,
    stats: PriceSummaryStats,
    extra_ground_truths: list[float] | None = None,
) -> ValidationResult:
    """
    Validate an LLM response against known DB values.

    Passes through:
    - Honest "I don't have data" responses
    - Responses with no numbers
    - Responses where all numbers match DB within 2%

    Suppresses:
    - Responses with numbers that deviate more than 2% from DB
    """
    # Pass through honest IDK responses unchanged
    idk_phrases = [
        "don't have reliable data",
        "cannot answer",
        "not available",
        "no data",
        "unable to provide",
    ]
    response_lower = response_text.lower()
    if any(phrase in response_lower for phrase in idk_phrases):
        return ValidationResult(passed=True, response=response_text)

    numbers = extract_numbers(response_text)
    ground_truths = _get_ground_truths(stats)
    if extra_ground_truths:
        ground_truths = ground_truths + [abs(v) for v in extra_ground_truths if v > 0]

    if not numbers:
        return ValidationResult(passed=True, response=response_text)

    violations = []
    for number in numbers:
        nearest = _find_nearest(number, ground_truths)
        if nearest is None:
            logger.debug("No ground truth for %s — skipping", number)
            continue

        deviation = abs(number - nearest) / nearest if nearest > 0 else 0
        if deviation > TOLERANCE_PCT:
            logger.warning(
                "Validation failed: claimed=%.4f actual=%.4f deviation=%.2f%%",
                number,
                nearest,
                deviation * 100,
            )
            violations.append(
                Violation(
                    claimed=number,
                    actual=nearest,
                    deviation=round(deviation * 100, 2),
                )
            )

    if violations:
        return ValidationResult(
            passed=False,
            violations=violations,
            response=IDK_RESPONSE,
        )

    return ValidationResult(passed=True, response=response_text)


MULTI_TOLERANCE_PCT = 0.05  # 5% tolerance for multi-stock comparisons


def validate_multi_response(
    response_text: str,
    all_stats: list[PriceSummaryStats],
) -> ValidationResult:
    """
    Validate an LLM response that compares multiple stocks.

    Builds a combined ground-truth pool from all stocks and uses a
    wider 5% tolerance, because:
    - Numbers from different stocks may be numerically close to each other,
      so the "nearest" match might belong to a different stock.
    - LLM rounding across multi-stock summaries is inherently less precise.

    Passes through:
    - Honest "I don't have data" responses
    - Responses with no numbers
    - Responses where all numbers are within 5% of at least one DB value
    """
    idk_phrases = [
        "don't have reliable data",
        "cannot answer",
        "not available",
        "no data",
        "unable to provide",
    ]
    if any(phrase in response_text.lower() for phrase in idk_phrases):
        return ValidationResult(passed=True, response=response_text)

    numbers = extract_numbers(response_text)
    if not numbers:
        return ValidationResult(passed=True, response=response_text)

    # Build a unified pool of ground truths from ALL stocks
    ground_truths: list[float] = []
    for st in all_stats:
        ground_truths.extend(
            [
                st.start_price,
                st.end_price,
                st.high_price,
                st.low_price,
                st.avg_price,
                abs(st.period_return_pct),
                st.volatility_pct,
            ]
        )

    violations = []
    for number in numbers:
        nearest = _find_nearest(number, ground_truths)
        if nearest is None:
            logger.debug("No ground truth for %s — skipping", number)
            continue

        deviation = abs(number - nearest) / nearest if nearest > 0 else 0
        if deviation > MULTI_TOLERANCE_PCT:
            logger.warning(
                "Multi validation failed: claimed=%.4f actual=%.4f deviation=%.2f%%",
                number,
                nearest,
                deviation * 100,
            )
            violations.append(
                Violation(
                    claimed=number,
                    actual=nearest,
                    deviation=round(deviation * 100, 2),
                )
            )

    if violations:
        return ValidationResult(
            passed=False,
            violations=violations,
            response=IDK_RESPONSE,
        )

    return ValidationResult(passed=True, response=response_text)
