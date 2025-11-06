#!/usr/bin/env python3
"""
Database initialization script for Video Streaming Platform.
- Creates database if it doesn't exist
- Creates user if it doesn't exist
- Runs all pending migrations
"""
import os
import sys
import time
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import alembic.config

# Add project root to path for imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.shared.database import get_connection_url

def wait_for_postgres(host, port, user, password, max_attempts=30, delay=2):
    """Wait for Postgres to become available"""
    print(f"Waiting for PostgreSQL at {host}:{port}...")
    
    for attempt in range(max_attempts):
        try:
            conn = psycopg2.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                dbname="postgres"  # Connect to default db first
            )
            conn.close()
            print("PostgreSQL is available!")
            return True
        except psycopg2.Error as e:
            if attempt < max_attempts - 1:
                print(f"Attempt {attempt + 1}/{max_attempts} failed: {str(e)}")
                time.sleep(delay)
            continue
    
    print(f"Error: PostgreSQL not available after {max_attempts} attempts")
    return False

def init_database(db_params):
    """Initialize database and user"""
    # Connect to default postgres database first
    conn = psycopg2.connect(
        host=db_params['host'],
        port=db_params['port'],
        user=db_params['admin_user'],
        password=db_params['admin_password'],
        dbname="postgres"
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    
    # Create user if not exists
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (db_params['app_user'],))
    if not cur.fetchone():
        print(f"Creating database user {db_params['app_user']}...")
        cur.execute(
            f"CREATE USER {db_params['app_user']} WITH PASSWORD %s",
            (db_params['app_password'],)
        )
    
    # Create database if not exists
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_params['dbname'],))
    if not cur.fetchone():
        print(f"Creating database {db_params['dbname']}...")
        cur.execute(f"CREATE DATABASE {db_params['dbname']} OWNER {db_params['app_user']}")
    
    cur.close()
    conn.close()
    
    # Now connect to the app database to create extensions if needed
    conn = psycopg2.connect(
        host=db_params['host'],
        port=db_params['port'],
        user=db_params['admin_user'],
        password=db_params['admin_password'],
        dbname=db_params['dbname']
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    
    # Add any required extensions
    extensions = ['uuid-ossp']  # Add more if needed
    for ext in extensions:
        cur.execute(f"CREATE EXTENSION IF NOT EXISTS \"{ext}\"")
    
    cur.close()
    conn.close()

def run_migrations():
    """Run all pending Alembic migrations"""
    print("Running database migrations...")
    os.chdir(PROJECT_ROOT)  # Alembic needs to run from project root
    alembic_cfg = alembic.config.Config("alembic.ini")
    alembic.command.upgrade(alembic_cfg, "head")

def main():
    # Get database configuration
    db_url = os.getenv('DATABASE_URL', 'postgresql://videouser:videopass@localhost:5432/video_streaming')
    admin_url = os.getenv('DATABASE_ADMIN_URL', 'postgresql://postgres:postgres@localhost:5432/postgres')
    
    # Parse connection URLs
    from urllib.parse import urlparse
    db_url = urlparse(db_url)
    admin_url = urlparse(admin_url)
    
    db_params = {
        'host': db_url.hostname or 'localhost',
        'port': db_url.port or 5432,
        'admin_user': admin_url.username or 'postgres',
        'admin_password': admin_url.password or 'postgres',
        'app_user': db_url.username,
        'app_password': db_url.password,
        'dbname': db_url.path[1:]  # Remove leading /
    }
    
    # Wait for PostgreSQL to be available
    if not wait_for_postgres(
        db_params['host'],
        db_params['port'],
        db_params['admin_user'],
        db_params['admin_password']
    ):
        sys.exit(1)
    
    try:
        # Initialize database and user
        init_database(db_params)
        
        # Run migrations
        run_migrations()
        
        print("Database initialization completed successfully!")
        return 0
        
    except Exception as e:
        print(f"Error during database initialization: {str(e)}", file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())