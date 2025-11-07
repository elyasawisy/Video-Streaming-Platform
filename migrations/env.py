"""Migration environment for Video Streaming Platform"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

import os
import sys

# Add project root to path for imports
config = context.config
if config.config_file_name is not None:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(config.config_file_name)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

# Import the models we want to work with. Avoid import-time DB connections.
target_metadata = None
try:
    # Prefer the upload_service models which declare Base
    from src.upload_service.models import Base  # type: ignore
    target_metadata = Base.metadata
except Exception:
    try:
        # Fallback: try streaming service models which may re-export Video
        from src.streaming_service.models import Video  # type: ignore
        # If models are present but no Base, leave target_metadata as None
        target_metadata = None
    except Exception:
        # Give up gracefully; alembic can still run without target_metadata
        target_metadata = None

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# target_metadata is set above based on available models (or None)

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

def get_url():
    """Get database URL from environment variable"""
    return os.getenv(
        "DATABASE_URL",
        "postgresql://videouser:videopass@localhost:5432/video_streaming"
    )

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()