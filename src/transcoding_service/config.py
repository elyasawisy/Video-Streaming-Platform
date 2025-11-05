"""
Configuration for Transcoding Service
"""
import os

class Config:
    DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://videouser:videopass@localhost:5432/video_streaming')
    RABBITMQ_URL = os.getenv('RABBITMQ_URL', 'amqp://guest:guest@localhost:5672/')
    RABBITMQ_QUEUE = 'transcode_queue'
    UPLOAD_DIR = os.getenv('UPLOAD_DIR', './uploads')
    RAW_DIR = os.path.join(UPLOAD_DIR, 'raw')
    TRANSCODED_DIR = os.path.join(UPLOAD_DIR, 'transcoded')
    GRPC_SERVER = os.getenv('GRPC_SERVER', 'localhost:50051')
    
    # Transcoding settings
    QUALITIES = ['360p', '480p', '720p', '1080p']
    FFMPEG_PRESET = 'medium'
    FFMPEG_CRF = 23
    
    # Worker settings
    WORKER_ID = os.getenv('WORKER_ID', f'worker-{os.getpid()}')
    POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', 5))  # seconds
    MAX_RETRIES = 3
    RETRY_DELAY = 10  # seconds

