"""Global pytest configuration and fixtures."""

import sqlalchemy.ext.asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine as original_create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

# SQLite has foreign keys disabled by default - In tests, ifyou could insert a PriceHistory row referencing a non existant ticket
# and SQLite would silently allow it - this is bad as it can hide bugs.
# so we use create_async_engine_with_fk in tests to ensure foreign keys are enabled and such bugs are caught early.

# pytest starts
#    → pytest_configure runs
#        → create_async_engine is patched globally
#            → any test creates an engine
#                → every new DB connection runs PRAGMA foreign_keys=ON
#                    → foreign key violations now raise errors in tests


# Wrap create_async_engine to add the foreign keys event listener
def create_async_engine_with_fk(*args, **kwargs):
    """Create an async engine with foreign keys enabled for SQLite."""
    url = str(args[0] if args else kwargs.get("url", ""))

    # asyncpg connections are bound to the event loop they were created on.
    # pytest-asyncio gives each test its own event loop (function scope by default).
    # Without NullPool, the connection pool reuses a connection created in a previous
    # test's event loop, which causes "Future attached to a different loop" errors.
    # NullPool is safe for Postgres tests: each session checkout creates a fresh connection.
    #
    # SQLite in-memory databases must NOT use NullPool — with NullPool every checkout
    # opens a brand-new connection to an empty in-memory DB, losing all setup state.
    # StaticPool (single shared connection) is the correct pool for in-memory SQLite tests.
    if "postgresql" in url:
        kwargs.setdefault("poolclass", NullPool)
    elif "sqlite" in url and ":memory:" in url:
        kwargs.setdefault("poolclass", StaticPool)

    engine = original_create_async_engine(*args, **kwargs)

    # Only register PRAGMA for SQLite — running PRAGMA on Postgres (asyncpg) sends
    # invalid SQL to the server, which aborts the transaction at the protocol level.
    # Even though the Python exception is caught, asyncpg leaves the connection in
    # a "transaction aborted" state, causing InFailedSQLTransactionError on the next query.
    url = str(args[0] if args else kwargs.get("url", ""))
    if "sqlite" not in url:
        return engine

    try:
        @event.listens_for(engine.sync_engine.pool, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            try:
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
            except Exception:  # noqa: S110
                pass
    except Exception:  # noqa: S110
        pass

    return engine


# pytest configure runs before any tests or foxture is loaded.
# it replaces the real async engine with the wrapped version so every test that creates an engine - will automatically gets foreign key enables
def pytest_configure(config):
    """Patch create_async_engine before any tests run."""
    sqlalchemy.ext.asyncio.create_async_engine = create_async_engine_with_fk
