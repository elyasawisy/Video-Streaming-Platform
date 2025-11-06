"""Enhanced database helpers with connection pooling and retry logic."""

import logging
import time
import functools
from typing import Any, Callable
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError, DBAPIError, OperationalError
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)

class DatabaseError(Exception):
    """Base exception for database errors."""
    pass

def retry_on_db_error(
    max_retries: int = 3,
    retry_delay: float = 1.0,
    exceptions: tuple = (OperationalError, DBAPIError)
) -> Callable:
    """Decorator for retrying database operations."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        delay = retry_delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(
                            f"Database operation failed (attempt {attempt + 1}/{max_retries}): {str(e)}. "
                            f"Retrying in {delay} seconds..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"Database operation failed after {max_retries} attempts: {str(e)}")
                        raise DatabaseError(f"Operation failed after {max_retries} attempts") from e
            return None  # Will never reach here due to raise in the loop
        return wrapper
    return decorator

def get_engine(
    DATABASE_URL: str,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    pool_recycle: int = 1800,  # Recycle connections after 30 minutes
    echo: bool = False
):
    """Create SQLAlchemy engine with enhanced connection pooling."""
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        pool_pre_ping=True,  # Verify connections before using them
        echo=echo
    )

    @event.listens_for(engine, 'connect')
    def on_connect(dbapi_connection, connection_record):
        """Set session parameters on connection."""
        logger.info("New database connection established")
        # Example: Set session parameters
        # cursor = dbapi_connection.cursor()
        # cursor.execute("SET timezone='UTC'")
        # cursor.close()

    @event.listens_for(engine, 'checkout')
    def on_checkout(dbapi_connection, connection_record, connection_proxy):
        """Verify connection is operational on checkout."""
        logger.debug("Database connection checked out from pool")

    @event.listens_for(engine, 'checkin')
    def on_checkin(dbapi_connection, connection_record):
        """Handle connection checkin."""
        logger.debug("Database connection returned to pool")

    return engine

def create_session_factory(DATABASE_URL: str, **kwargs):
    """Create a sessionmaker with automatic session closing."""
    engine = get_engine(DATABASE_URL, **kwargs)
    session_factory = sessionmaker(bind=engine)

    @event.listens_for(Session, 'after_begin')
    def after_begin(session, transaction, connection):
        """Log transaction begin."""
        logger.debug("Database transaction started")

    @event.listens_for(Session, 'after_commit')
    def after_commit(session):
        """Log transaction commit."""
        logger.debug("Database transaction committed")

    @event.listens_for(Session, 'after_rollback')
    def after_rollback(session):
        """Log transaction rollback."""
        logger.debug("Database transaction rolled back")

    return session_factory

class SessionManager:
    """Context manager for database sessions."""
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def __enter__(self):
        self.session = self.session_factory()
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            # On error, rollback
            self.session.rollback()
            logger.error(f"Database error occurred: {exc_type.__name__}: {str(exc_val)}")
        try:
            # Always close the session
            self.session.close()
        except Exception as e:
            logger.error(f"Error closing database session: {str(e)}")
            raise DatabaseError("Failed to close database session") from e
