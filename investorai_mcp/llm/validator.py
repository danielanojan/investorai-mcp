"""
Post-generation validator. 

Extracts every financial number from LLM responses and
verifies each against the database within 0.5% tolerance. 
If any number fails verification the response is supressed. 

This si the zero-hallucination gurantee for InvestorAI. 
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import date

from investorai_mcp.llm.prompt_builder import PriceSummaryStats

logger = logging.getLogger(__name__)

#Tolerance - how far off a number can be before it's flagged. 
TOLERANCE_PCT = 0.005 # 0.5%

#response returned when validation fails
IDK_RESPONSE = (
    "I don't have reliable data to answer this accurately. "
    "Please check a financial data source directly for precise figures. "
)

#---- Number extraction patterns ----------------------------------
#Order matters - more specific pattern first
_PATTERNS = [
    # $1,234.56 or $1234.56 or $1,234
    r"\$([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)",
    # 12.3% or 12% or -5.4% or +12.3%
    r"[+-]?([0-9]+(?:\.[0-9]+)?)\s*%",
    # 1.2B or 1.2b (billions)
    r"([0-9]+(?:\.[0-9]+)?)\s*[Bb](?:illion)?",
    # 1.2T or 1.2t (trillions)
    r"([0-9]+(?:\.[0-9]+)?)\s*[Tt](?:rillion)?",
    # Plain decimal number with 2+ decimal places (prices)
    # Excludes years (2026) and small integers
    r"\b([0-9]{1,4}\.[0-9]{2,})\b",
]

_COMPILED = [re.compile(p) for p in _PATTERNS]

# Numbers to exclude from validation — years, quantities, etc.
_EXCLUDE_PATTERNS = [
    re.compile(r"^20[0-9]{2}$"),   # years like 2026
    re.compile(r"^[0-9]$"),         # single digits
    re.compile(r"^[0-9]{2}$"),      # two digit numbers (e.g. "50 stocks")
]

# ── Data classes ──────────────────────────────────────────────────────────

@dataclass
class Violation:
    """A number in the response that doesn't match the DB"""
    claimed : float
    actual: float
    deviation: float   # as a percentage
    
@dataclass
class ValidationResult:
    """ A number in the response that doesn't match the DB"""
    passed : bool
    violations: list[Violation] = field(default_factory=list)
    response: str = ""  # original response from LLM, for logging/debugging
    

#--- Number extraction and validation logic ----------------------------------

def extract_numbers(text: str) -> list[float]:
    """
    Extract all financial numbers from response text. 
    
    Handles: $174.32, 12.3%, 1.2B, 1.2T, 174.32
    Excludes: years (2026), single/double digit integers

    Returns list of floats - deduplicated and sorted
    """
    numbers = set()
    
    for pattern in _COMPILED:
        for match in pattern.finditer(text):
            raw = match.group(1).replace(",", "")
            try:
                value = float(raw)
                
                # apply billion/trillions multipliers
                full_match = match.group(0).lower()
                if "b" in full_match and "%" not in full_match:
                    value *= 1_000_000_000
                elif "t" in full_match and "%" not in full_match:
                    value *= 1_000_000_000_000
            
                #skip excluded patterns
                if any(p.match(str(int(value))) for p in _EXCLUDE_PATTERNS
                    if value == int(value)):
                    
                    continue
                
                # skip very small numbers (rounding artifacts)
                if value < 0.01:
                    continue
                
                numbers.add(round(value, 4)) # round to 4 decimals to avoid tiny float differences
            
            except (ValueError, OverflowError):
                continue
            
    return sorted(numbers)

def _get_ground_truths(stats: PriceSummaryStats) -> list[float]:
    """
    Get all relevant numbers from stats for validation
    These are values the LLM is allowed to cite. 
    """
    return [
        stats.start_price,
        stats.end_price,
        stats.high_price,
        stats.low_price,
        stats.avg_price,
        abs(stats.period_return_pct),
        stats.volatality_pct,
        float(stats.trading_days),
    ]

    
def _find_nearest(value: float, ground_truths: list[float]) -> float | None:
    """
    Find the closest ground truth value to the claimed number. 
    """
    if not ground_truths:
        return None
    
    # only compare values in a similar magnitude range
    candidates = [
        gt for gt in ground_truths
        if gt > 0 and abs(gt - value) / max(gt, value) < 0.5  
    ]
    
    if not candidates:
        return None
    
    return min(candidates, key=lambda gt: abs(gt - value))
    
# ---- Validator -----------------------------------------------

def validate_response(
    response_text: str,
    stats: PriceSummaryStats,
) -> ValidationResult:
    """
    Validate an LLM response against known DB values.
    
    Extracts all numbers from the response and checks each
    aganinst the PriceSummaryStats within TOLERANCE_PCT. 
    
    Args:
        response_text: The raw LLM response string. 
        stats: Pre computed stats used to build the prompt. 
        
    Returns:
        ValidationResult with passed=True if all numbers check out, 
        or passed = False with violations list if any fail.  
    """
    numbers = extract_numbers(response_text)
    ground_truths = _get_ground_truths(stats)
    
    if not numbers:
        # No numbers in response - nothing to validate. 
        return ValidationResult(
            passed=True,
            response=response_text
        )
    
    violations = []
    
    for number in numbers:
        nearest = _find_nearest(number, ground_truths)
        
        if nearest is None:
            # Can't find any comparable ground truth - treat as a violation.
            logger.warning("Validation failed: no ground truth found for claimed=%s", number)
            violations.append(Violation(
                claimed=number,
                actual=0.0,
                deviation=100.0,
            ))
            continue
        
        deviation = abs(number - nearest) / nearest if nearest > 0 else 0
        
        if deviation > TOLERANCE_PCT:
            logger.warning(
                "Validation failed: claimed=%.4f actual=%.4f deviation=%.2f%%",
                number, nearest, deviation * 100,
            ) 
            violations.append(Violation(
                claimed=number,
                actual=nearest,
                deviation=round(deviation * 100, 2)
            ))
    
    if violations:
        return ValidationResult(
            passed=False,
            violations=violations,
            response=IDK_RESPONSE
        )
        
    return ValidationResult(
        passed=True,
        response=response_text,
    )
    