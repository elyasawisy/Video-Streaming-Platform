"""
Configuration for Streaming Service
Optimized for high concurrency (50k+ viewers)
"""
import os

class Config:
    DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://videouser:videopass@localhost:5432/video_streaming')
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
    UPLOAD_DIR = os.getenv('UPLOAD_DIR', './uploads')
    RAW_DIR = os.path.join(UPLOAD_DIR, 'raw')
    TRANSCODED_DIR = os.path.join(UPLOAD_DIR, 'transcoded')
    
    # Streaming settings
    CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', 1024 * 1024))  # 1MB chunks
    MAX_RANGE_SIZE = int(os.getenv('MAX_RANGE_SIZE', 10 * 1024 * 1024))  # 10MB max range
    CACHE_TTL = int(os.getenv('CACHE_TTL', 3600))  # 1 hour cache
    
    # Performance settings
    MAX_WORKERS = int(os.getenv('MAX_WORKERS', 100))
    KEEP_ALIVE_TIMEOUT = int(os.getenv('KEEP_ALIVE_TIMEOUT', 65))
    MAX_CONNECTIONS = int(os.getenv('MAX_CONNECTIONS', 10000))
    
    # CORS settings
    ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', '*').split(',')

