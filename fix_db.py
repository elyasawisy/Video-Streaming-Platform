import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://videouser:videopass@localhost:5432/video_streaming')

def fix_db():
    # Create engine
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        # Start transaction
        with conn.begin():
            # First drop the alembic_version table to reset migration state
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
            
            # Drop and recreate chunked_uploads table with correct schema
            conn.execute(text("""
                DROP TABLE IF EXISTS chunked_uploads CASCADE;
                
                CREATE TABLE chunked_uploads (
                    id UUID DEFAULT uuid_generate_v4() NOT NULL,
                    video_id UUID REFERENCES videos(id) ON DELETE CASCADE,
                    filename VARCHAR(255) NOT NULL,
                    total_chunks INTEGER NOT NULL,
                    chunk_size INTEGER NOT NULL DEFAULT 1048576,
                    file_size BIGINT NOT NULL,
                    uploaded_chunks INTEGER NOT NULL DEFAULT 0,
                    is_complete BOOLEAN NOT NULL DEFAULT false,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP WITH TIME ZONE,
                    expires_at TIMESTAMP WITH TIME ZONE,
                    status VARCHAR(50) NOT NULL DEFAULT 'pending',
                    PRIMARY KEY (id)
                );
                
                CREATE INDEX idx_chunked_uploads_video_id ON chunked_uploads(video_id);
            """))
            
            # Set the alembic version to current head
            conn.execute(text("""
                CREATE TABLE alembic_version (
                    version_num VARCHAR(32) NOT NULL,
                    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
                );
                INSERT INTO alembic_version (version_num) VALUES ('006');
            """))

if __name__ == '__main__':
    fix_db()