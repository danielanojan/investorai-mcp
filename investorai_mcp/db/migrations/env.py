import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection

from investorai_mcp.db.models import Base

#alembic runs this everytime when migration command is executed. 


# Load .env so DATABASE_URL is available when running alembic from CLI
load_dotenv(Path(__file__).parents[3] / ".env")

config = context.config

database_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./investorai.db")

# Alembic uses synchronous engines — strip async driver prefixes and replace with sync equivalents. 
sync_url = (
    database_url
    .replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    .replace("sqlite+aiosqlite://", "sqlite://")
)

config.set_main_option("sqlalchemy.url", sync_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# schema is stored in Base.metadata - 
# we will use it for autogeneration of migration scripts.
target_metadata = Base.metadata

#this runs migrations without actual DB connections. 
# this generates SQL to stdout ot a file. 
# this is used for review. 
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch="sqlite" in sync_url,
    )
    with context.begin_transaction():
        context.run_migrations()

# this creates a syncronous engine visa engine_from_confic. 
#usual path to run migrations. It connects and run migrations in reallive DB. 
# NullPool is used - so connections aren't pooled - each migration will get fresh connection and releases immediately. 
def do_run_migrations(connection: Connection) -> None:
    if "sqlite" in sync_url:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch="sqlite" in sync_url,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        do_run_migrations(connection)
    connectable.dispose()

#entry point - select online/ offline and run accordingly. 
# Alembic will call this when you run alembic command in CLI.
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
