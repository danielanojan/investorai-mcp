"""
Input sanitization for the FastAPI boundary layer.

All user-controlled values are validated here before reaching the DB or LLM.
The ORM parameterizes queries so SQL injection is already prevented at that layer;
these checks are defense-in-depth — reject obviously malformed input early.
"""

import re

# Ticker symbols: 1–5 uppercase letters, optional hyphen + 1 uppercase letter (e.g. BRK-B)
_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(?:-[A-Z])?$")

# Question length cap — long enough for any real query, short enough to block abuse
MAX_QUESTION_LEN = 2000

# Model whitelist — only pass known model IDs to litellm
ALLOWED_MODELS: frozenset[str] = frozenset(
    [
        # Anthropic
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
        "claude-haiku-4-5-20251001",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        # OpenAI
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
        # Groq
        "groq/llama-3.3-70b-versatile",
        "groq/llama-3.1-8b-instant",
        "groq/mixtral-8x7b-32768",
    ]
)


def validate_symbol(symbol: str) -> str:
    """Normalize and validate a ticker symbol.

    Returns the uppercased symbol if valid. Raises ValueError for anything
    that doesn't match the expected format, before the SUPPORTED_TICKERS check.
    """
    s = symbol.strip().upper()
    if not _SYMBOL_RE.match(s):
        raise ValueError(f"Invalid ticker symbol format: {symbol!r}")
    return s


def validate_question(question: str) -> str:
    """Strip and length-cap a user question. Raises ValueError if too long."""
    q = question.strip()
    if len(q) > MAX_QUESTION_LEN:
        raise ValueError(f"Question exceeds maximum length of {MAX_QUESTION_LEN} characters.")
    return q


def validate_model(model: str) -> str:
    """Ensure the model ID is in the known allowlist. Raises ValueError if not."""
    if model not in ALLOWED_MODELS:
        raise ValueError(
            f"Model {model!r} is not supported. "
            f"Allowed models: {', '.join(sorted(ALLOWED_MODELS))}"
        )
    return model
