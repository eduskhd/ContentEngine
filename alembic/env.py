from logging.config import fileConfig
from sqlalchemy import create_engine, event
from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No ORM models — all migrations are raw SQL via op.execute()
target_metadata = None


def _configure_sqlite(dbapi_conn, connection_record):
    """Activate WAL mode and FK enforcement on every new SQLite connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def run_migrations_offline() -> None:
    """Emit migration SQL to stdout without a live connection (dry-run)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against the live database."""
    url = config.get_main_option("sqlalchemy.url")
    connectable = create_engine(url, connect_args={"timeout": 30})
    event.listen(connectable, "connect", _configure_sqlite)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
