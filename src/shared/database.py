"""Database helpers shared across services."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# TODO: pass DATABASE_URL from environment of each service
def get_engine(database_url: str):
    """Create SQLAlchemy engine with sane defaults."""
    return create_engine(database_url, pool_pre_ping=True)


def create_session_factory(database_url: str):
    """Create a sessionmaker bound to the provided engine."""
    engine = get_engine(database_url)
    return sessionmaker(bind=engine)

