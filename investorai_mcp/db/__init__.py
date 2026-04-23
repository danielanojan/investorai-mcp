import asyncio
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from investorai_mcp.config import settings

# this is db initialization and session management module. It sets up DB engine, run migration on startup and provide sessions to rest of the app.

"""
Server starts
    → init_db() called
        → _run_alembic_upgrade() runs in thread pool
            → Alembic checks pending migrations
                → applies any new ones to the DB

Request comes in
    → get_session() provides a fresh AsyncSession
        → route handler does DB work
            → session closes automatically

"""

# echo - don't print SQL statement to console - Set True for debugging
# connect args - SQLite specific. By default SqLite allows only the thread which created the connection to use it. This disables the restriction
# setting check_same_thread=False is important in async thread - since different threads may share a connection.

# poolclass=StaticPool - uses single persistant connection instead of a pool. Its important for SQL in tests and single process apps because
# SQLite does not handle multiple connections to the same file well. StaticPool ensures all parts of the app use the same connection, which is safer for SQLite's concurrency model.


database_url = os.environ.get("DATABASE_URL", settings.database_url)

# Railway provides postgresql:// but SQLAlchemy needs postgresql+asyncpg://
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(
    database_url,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in database_url else {},
)

# SQLite pragmas — WAL mode + busy timeout to serialise concurrent writers
if "sqlite" in database_url:

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")  # queue writers instead of failing
        cursor.execute("PRAGMA busy_timeout=5000")  # wait up to 5s before erroring
        cursor.close()


# creates asyncSession object on demand. After session.commit() - python object should not expire and can still be used without needing to refresh from the database.
# This is important for our use case where we often want to return newly created or updated objects immediately after commit without needing an extra query to refresh them.
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# its a syncronous function which runs all pending alembic migrations. It has to be sync because Alembic's command.upgrade is a blocking call
# it does not support async.
def _run_alembic_upgrade() -> None:
    """Run alembic migrations syncronously (called from async context via executor)"""
    import os
    from pathlib import Path

    from sqlalchemy.exc import OperationalError

    # Get the project root (two levels up from this file)
    project_root = Path(__file__).parent.parent.parent  # go to where alembic.ini lives
    alembic_ini_path = project_root / "alembic.ini"

    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option(
        "sqlalchemy.url", os.environ.get("DATABASE_URL", settings.database_url)
    )
    try:
        command.upgrade(alembic_cfg, "head")  # run all migrations up to the latest one
    except OperationalError as exc:
        # If tables already exist but alembic_version is missing, align migration state.
        if "already exists" in str(exc).lower():
            command.stamp(alembic_cfg, "head")
            return
        raise


# async wrapper around run_alembic operator. It runs blocking Alembic command in a thread pool - do it does not freeze the async event loop.
# this is called once at server startup - so db schema is always up ensuring db schema is always upto date before handling requests.
async def init_db() -> None:
    """Run all pending alembic migrations. Called once at server startup"""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_alembic_upgrade)


# dependency provider. will be used with fastaAPI's dependency injection.
async def get_session() -> AsyncSession:
    """Provide a transactional scope around a series of operations."""
    async with AsyncSessionLocal() as session:
        yield session
