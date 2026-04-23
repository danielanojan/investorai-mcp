"""
Standard Error envelope for all BFF endpoints.
"""

import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded


def make_error(code: str, message: str, detail: str = "") -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": detail,
            "request_id": f"req_{uuid.uuid4().hex[:8]}",
        }
    }


async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content=make_error(
            "RATE_LIMIT_EXCEEDED",
            "Too many requests - please slow down.",
            "Refer to API documentation for rate limits.",
        ),
    )
