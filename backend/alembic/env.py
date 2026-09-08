"""
Alembic env.py — wires Alembic to our SQLAlchemy models and config.

Key decisions:
  • We import `Base.metadata` from our models so autogenerate can diff
    the ORM against the live DB.
  • We use the *sync* engine (psycopg2) because Alembic doesn't natively
    support async migrations.
  • The DB URL comes from `app.config.settings`, not from alembic.ini,
    so there's a single source of truth.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

from app.config import settings
from app.db.engine import sync_engine
from app.db.models import Base            # noqa: F401  — ensure models are registered

# ── Alembic Config ────────────────────────────────────────
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emit SQL to stdout."""
    context.configure(
        url=settings.database_url_sync,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — execute against a live DB."""
    connectable = sync_engine

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
