"""
Rate limiting for the FastAPI BFF.
Uses SlowAPI (Starlette-compatible limiter backed by in-memory store)

"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
