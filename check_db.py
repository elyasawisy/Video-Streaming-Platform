import os
from sqlalchemy import create_engine, inspect

# Get database URL from environment or use default
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://videouser:videopass@localhost:5432/video_streaming')

# Create engine
engine = create_engine(DATABASE_URL)

# Create inspector
inspector = inspect(engine)

# Get all tables
for table_name in inspector.get_table_names():
    print(f"\nTable: {table_name}")
    print("Columns:")
    for column in inspector.get_columns(table_name):
        print(f"  - {column['name']}: {column['type']}")