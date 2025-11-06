#!/bin/bash
set -e

# Function to initialize database if needed
init_db() {
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Enable needed extensions
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    CREATE EXTENSION IF NOT EXISTS "hstore";

    -- Create initial schema
    -- Videos table
    CREATE TABLE IF NOT EXISTS videos (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        title VARCHAR(255) NOT NULL,
        filename VARCHAR(255) NOT NULL,
        original_filename VARCHAR(255),
        file_size BIGINT NOT NULL DEFAULT 0,
        file_hash VARCHAR(64),
        mime_type VARCHAR(100),
        status VARCHAR(50) NOT NULL,
        upload_method VARCHAR(50) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        uploaded_at TIMESTAMP WITH TIME ZONE,
        transcoded_at TIMESTAMP WITH TIME ZONE,
        deleted_at TIMESTAMP WITH TIME ZONE,
        uploader_id VARCHAR(255),
        duration INTEGER,
        description TEXT,
        thumbnail_path VARCHAR(255),
        is_public BOOLEAN DEFAULT true,
        view_count INTEGER DEFAULT 0,
        like_count INTEGER DEFAULT 0,
        tags JSONB,
        category VARCHAR(100),
        quality_available JSONB
    );

    -- Upload metrics table
    CREATE TABLE IF NOT EXISTS upload_metrics (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        video_id UUID REFERENCES videos(id),
        upload_method VARCHAR(50) NOT NULL,
        file_size BIGINT NOT NULL,
        upload_duration INTEGER NOT NULL,
        throughput BIGINT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- Chunked uploads table
    CREATE TABLE IF NOT EXISTS chunked_uploads (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        video_id UUID REFERENCES videos(id),
        filename VARCHAR(255) NOT NULL,
        total_chunks INTEGER NOT NULL,
        chunk_size INTEGER NOT NULL,
        total_size BIGINT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP WITH TIME ZONE,
        status VARCHAR(50) NOT NULL
    );

    -- Create indexes
    CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
    CREATE INDEX IF NOT EXISTS idx_videos_uploader ON videos(uploader_id);
    CREATE INDEX IF NOT EXISTS idx_videos_created_at ON videos(created_at);
    CREATE INDEX IF NOT EXISTS idx_upload_metrics_method ON upload_metrics(upload_method);
    CREATE INDEX IF NOT EXISTS idx_chunked_uploads_video_id ON chunked_uploads(video_id);
EOSQL
}

# Initialize database
init_db

echo "Database initialization completed"