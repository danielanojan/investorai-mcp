import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# import all models - so alembic can detect them
from investorai_mcp.db.models import Base

"""
overall flow

alembic upgrade head
    → env.py runs
        → loads models via Base.metadata
        → reads DATABASE_URL
        → is_offline_mode()? No
            → run_migrations_online()
                → asyncio.run(run_async_migrations())
                    → creates async engine
                        → opens connection
                            → PRAGMA foreign_keys=ON
                            → context.run_migrations()
                                → applies pending versions/
                                    001_create_tickers.py
                                    002_create_price_history.py
                                    ...
"""
# alembic needs to see all yout models - so tit can diff them against the actual db and generate accurate migrations.
# if a model is not imported here alembic wont know it exists.

config = context.config

# overrides URL from alembic.ini with the environment variable if set. default fallback is investorai.db -
# in fallback db is created in the current directory.
database_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./investorai.db")


config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# telling alembic to compare migrations against your SQLAlchemy model definitions. this will enable --autogenerate to work.
target_metadata = Base.metadata

# alembic have two modes. It can run offline or online.


# in offline mode - it generates SQL scripts without connecting to the DB. Its useful when you need to review SQL before running it or
# when you don't have db access.
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,  # renders actual values in SQL instead of ? placeholders.
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # for SQLite migrations which alter tables. SQLite cannot do Alter Table directly. batch mode works around this by create new table, copy data and drop old table.
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # Enable foreign keys for SQLite
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # for SQLite migrations which alter tables
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


# here it will be the entry point for online mode. Everything is async so async.run() used for async migration function from syncronous context.
def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
