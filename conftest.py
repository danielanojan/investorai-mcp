"""Global pytest configuration and fixtures."""

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine as original_create_async_engine
import sqlalchemy.ext.asyncio

#SQLite has foreign keys disabled by default - In tests, ifyou could insert a PriceHistory row referencing a non existant ticket
# and SQLite would silently allow it - this is bad as it can hide bugs. 
# so we use create_async_engine_with_fk in tests to ensure foreign keys are enabled and such bugs are caught early.

#pytest starts
#    → pytest_configure runs
#        → create_async_engine is patched globally
#            → any test creates an engine
#                → every new DB connection runs PRAGMA foreign_keys=ON
#                    → foreign key violations now raise errors in tests

# Wrap create_async_engine to add the foreign keys event listener
def create_async_engine_with_fk(*args, **kwargs):
    """Create an async engine with foreign keys enabled for SQLite."""
    #this adds extra behaviour on top of the original async engine. 
    # We call the original to get the engine, then add an event listener to enable foreign keys on connect.
    engine = original_create_async_engine(*args, **kwargs)
    
        # Listen for the "connect" event to enable foreign keys for SQLite
        
        #every time a new database connection is opeed from the pool - it immediately runs PRAGMA foreign_keys=ON 
        # to ensure that foreign key constraints are enforced for the duration of that connection.
    try:
        @event.listens_for(engine.sync_engine.pool, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            try:
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
            except Exception:
                pass
    except Exception:
        pass
    
    return engine

#pytest configure runs before any tests or foxture is loaded. 
#it replaces the real async engine with the wrapped version so every test that creates an engine - will automatically gets foreign key enables 
def pytest_configure(config):
    """Patch create_async_engine before any tests run."""
    sqlalchemy.ext.asyncio.create_async_engine = create_async_engine_with_fk





