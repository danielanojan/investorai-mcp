"""
This integration test is for Alembic migrations and db init. 
Run thsis against a temporary sqlite file - not in memory-
because alembic reads alembic.ini from disk
"""

import os

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine


def make_db_url(path: str) -> str:
    return f"sqlite+aiosqlite:///{path}"

async def get_tables(db_url: str) -> list[str]:
    eng = create_async_engine(db_url, echo=False)
    async with eng.connect() as conn:
        tables = await conn.run_sync(lambda c:inspect(c).get_table_names())
    await eng.dispose()
    return tables

async def get_pragma(db_url: str, pragma: str):
    eng = create_async_engine(db_url, echo=False)
    async with eng.connect() as conn:
        result = await conn.exec_driver_sql(f"PRAGMA {pragma}")
        row = result.fetchone()
    await eng.dispose()
    return row[0] if row else None

@pytest.fixture
def tmp_db(tmp_path):
    db_file = str(tmp_path / "test.db")
    db_url = make_db_url(db_file)
    os.environ["DATABASE_URL"] = db_url
    yield db_file, db_url
    os.environ.pop("DATABASE_URL", None)
    
async def test_all_six_tables_created(tmp_db):
    db_file, db_url = tmp_db
    from investorai_mcp.db import init_db
    await init_db()
    tables = await get_tables(db_url)
    for t in ["tickers", "price_history", "news_articles", "cache_metadata", "eval_log", "llm_usage_log"]:
        assert t in tables, f"Expected table '{t}' not found in database"
        
        
async def test_wal_mode_enabled(tmp_db):
    db_file, db_url = tmp_db
    from investorai_mcp.db import init_db
    await init_db()
    mode = await get_pragma(db_url, "journal_mode")
    assert mode == "wal", f"Expected WAL mode, but got {mode}"
    
async def test_foreign_keys_enabled(tmp_db):
    db_file, db_url = tmp_db
    from investorai_mcp.db import init_db
    await init_db()
    fk = await get_pragma(db_url, "foreign_keys")
    assert fk == 1, f"Expected foreign_keys to be ON (1), but got {fk}"
    