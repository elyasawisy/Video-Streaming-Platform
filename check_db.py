import os
from sqlalchemy import create_engine, inspect, text

# Get database URL from environment or use default
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://videouser:videopass@localhost:5432/video_streaming')

def check_db():
    # Create engine
    engine = create_engine(DATABASE_URL)
    
    try:
        # First test connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).scalar()
            print("Database connection successful")
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return

    # Create inspector
    inspector = inspect(engine)

    if 'chunked_uploads' not in inspector.get_table_names():
        print("chunked_uploads table not found!")
        return

    print("\nChecking chunked_uploads table structure:")
    for column in inspector.get_columns('chunked_uploads'):
        print(f"Column: {column['name']}")
        print(f"  Type: {column['type']}")
        print(f"  Nullable: {column['nullable']}")
        if 'default' in column:
            print(f"  Default: {column['default']}")
        print()

    # Check for any existing rows
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM chunked_uploads")).scalar()
        print(f"\nTotal rows in chunked_uploads: {result}")

if __name__ == '__main__':
    check_db()