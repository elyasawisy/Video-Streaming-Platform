"""Database migration utilities using Alembic."""

import os
import sys
from alembic import command
from alembic.config import Config
from pathlib import Path

def get_project_root():
    """Get the project root directory."""
    current_dir = Path(__file__).parent
    while not (current_dir / 'requirements.txt').exists():
        current_dir = current_dir.parent
        if current_dir == current_dir.parent:  # Reached filesystem root
            raise RuntimeError("Could not find project root")
    return current_dir

def create_alembic_config(db_url=None):
    """Create Alembic configuration."""
    project_root = get_project_root()
    migrations_dir = project_root / 'migrations'
    migrations_dir.mkdir(exist_ok=True)

    # Create alembic.ini if it doesn't exist
    alembic_ini = project_root / 'alembic.ini'
    if not alembic_ini.exists():
        template = f"""\
[alembic]
script_location = migrations
sqlalchemy.url = {db_url or 'driver://user:pass@localhost/dbname'}

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
"""
        alembic_ini.write_text(template)

    # Create env.py if it doesn't exist
    env_py = migrations_dir / 'env.py'
    if not env_py.exists():
        template = """\
from logging.config import fileConfig

from sqlalchemy import create_engine
from alembic import context

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from src.upload_service.models import Base

# This is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    configuration = config.get_section(config.config_ini_section)
    url = configuration["sqlalchemy.url"]
    connectable = create_engine(url)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
"""
        env_py.write_text(template)

def init_migrations(db_url=None):
    """Initialize database migrations."""
    alembic_cfg = create_alembic_config(db_url)
    command.init(alembic_cfg, 'migrations')

def create_migration(message):
    """Create a new migration."""
    alembic_cfg = Config('alembic.ini')
    command.revision(alembic_cfg, message=message, autogenerate=True)

def upgrade_database(revision='head'):
    """Upgrade database to a revision."""
    alembic_cfg = Config('alembic.ini')
    command.upgrade(alembic_cfg, revision)

def downgrade_database(revision='-1'):
    """Downgrade database to a revision."""
    alembic_cfg = Config('alembic.ini')
    command.downgrade(alembic_cfg, revision)

def check_migrations():
    """Check if any migrations need to be applied."""
    alembic_cfg = Config('alembic.ini')
    return command.check(alembic_cfg)