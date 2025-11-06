"""Enhanced Chunked Upload Service with validation, progress tracking, and cleanup."""

import os
import uuid
import hashlib
import time
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
from threading import Lock
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import pika
import redis
from sqlalchemy import create_engine, Column, String, Integer, DateTime, BigInteger, Enum, Boolean, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import QueuePool
import enum
from prometheus_client import Counter, Histogram, start_http_server

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('chunked_upload.log')
    ]
)
logger = logging.getLogger(__name__)

# Prometheus metrics
UPLOAD_STARTED = Counter('chunked_upload_started_total', 'Total uploads started')
UPLOAD_COMPLETED = Counter('chunked_upload_completed_total', 'Total uploads completed')
UPLOAD_FAILED = Counter('chunked_upload_failed_total', 'Total uploads failed')
CHUNK_UPLOADED = Counter('chunked_upload_chunks_total', 'Total chunks uploaded')
CHUNK_FAILED = Counter('chunked_upload_chunks_failed_total', 'Total chunks failed')
UPLOAD_DURATION = Histogram('chunked_upload_duration_seconds', 'Upload duration in seconds')
CHUNK_SIZE = Histogram('chunked_upload_chunk_size_bytes', 'Chunk size in bytes')

@dataclass
class ChunkMetadata:
    """Metadata for a single chunk."""
    number: int
    size: int
    md5: str
    uploaded_at: datetime
    retry_count: int = 0

class Config:
    """Enhanced configuration with validation and metrics settings."""
    # Database
    DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://videouser:videopass@localhost:5432/video_streaming')
    DB_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', 5))
    DB_MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', 10))
    DB_POOL_TIMEOUT = int(os.getenv('DB_POOL_TIMEOUT', 30))
    DB_POOL_RECYCLE = int(os.getenv('DB_POOL_RECYCLE', 1800))  # 30 minutes

    # RabbitMQ
    RABBITMQ_URL = os.getenv('RABBITMQ_URL', 'amqp://guest:guest@localhost:5672/')
    RABBITMQ_QUEUE = os.getenv('RABBITMQ_QUEUE', 'transcode_queue')
    RABBITMQ_RETRY_QUEUE = os.getenv('RABBITMQ_RETRY_QUEUE', 'transcode_retry')
    RABBITMQ_DLQ = os.getenv('RABBITMQ_DLQ', 'transcode_dlq')
    RABBITMQ_EXCHANGE = os.getenv('RABBITMQ_EXCHANGE', 'video_exchange')
    RABBITMQ_MAX_RETRIES = int(os.getenv('RABBITMQ_MAX_RETRIES', 3))

    # Redis
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
    REDIS_TIMEOUT = int(os.getenv('REDIS_TIMEOUT', 5))
    REDIS_RETRY_INTERVAL = int(os.getenv('REDIS_RETRY_INTERVAL', 1))
    REDIS_MAX_RETRIES = int(os.getenv('REDIS_MAX_RETRIES', 3))

    # Upload settings
    UPLOAD_DIR = os.getenv('UPLOAD_DIR', './uploads')
    CHUNKS_DIR = os.path.join(UPLOAD_DIR, 'chunks')
    RAW_DIR = os.path.join(UPLOAD_DIR, 'raw')
    MAX_UPLOAD_SIZE = int(os.getenv('MAX_UPLOAD_SIZE', 2 * 1024 * 1024 * 1024))  # 2GB
    MIN_CHUNK_SIZE = 64 * 1024  # 64KB minimum
    MAX_CHUNK_SIZE = 8 * 1024 * 1024  # 8MB maximum
    CHUNK_SIZE = 1024 * 1024  # 1MB default
    MAX_CHUNKS = int(os.getenv('MAX_CHUNKS', 10000))
    UPLOAD_EXPIRY = int(os.getenv('UPLOAD_EXPIRY', 24 * 3600))  # 24 hours
    CLEANUP_INTERVAL = int(os.getenv('CLEANUP_INTERVAL', 3600))  # 1 hour

    # File validation
    ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'flv', 'wmv'}
    ALLOWED_MIME_TYPES = {
        'video/mp4', 'video/x-msvideo', 'video/quicktime',
        'video/x-matroska', 'video/x-flv', 'video/x-ms-wmv'
    }
    MAX_FILENAME_LENGTH = 255
    
    # Security
    FILE_HASH_ALGO = 'sha256'
    CHUNK_HASH_ALGO = 'md5'  # Faster for chunks
    API_KEY_HEADER = 'X-API-Key'

    # Rate limiting
    RATE_LIMIT_ENABLED = True
    RATE_LIMIT_WINDOW = 3600  # 1 hour
    RATE_LIMIT_MAX_UPLOADS = 100
    RATE_LIMIT_MAX_CHUNKS = 1000

    # Metrics
    METRICS_ENABLED = os.getenv('METRICS_ENABLED', 'true').lower() == 'true'
    METRICS_PORT = int(os.getenv('METRICS_PORT', 9102))

class ChunkManager:
    """Enhanced chunk management with validation and cleanup."""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.locks: Dict[str, Lock] = {}
        self.chunk_locks: Dict[str, Lock] = {}

    def _get_upload_key(self, upload_id: str) -> str:
        """Get Redis key for upload metadata."""
        return f"upload:{upload_id}"

    def _get_chunk_key(self, upload_id: str, chunk_number: int) -> str:
        """Get Redis key for chunk metadata."""
        return f"chunk:{upload_id}:{chunk_number}"

    def _get_lock(self, key: str) -> Lock:
        """Get or create a lock for concurrent access."""
        if key not in self.locks:
            self.locks[key] = Lock()
        return self.locks[key]

    def validate_chunk(
        self,
        chunk_path: str,
        expected_size: Optional[int] = None,
        expected_hash: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """Validate chunk size and hash."""
        try:
            if not os.path.exists(chunk_path):
                return False, "Chunk file not found"

            actual_size = os.path.getsize(chunk_path)
            
            if expected_size and actual_size != expected_size:
                return False, f"Size mismatch: expected {expected_size}, got {actual_size}"

            if expected_hash:
                with open(chunk_path, 'rb') as f:
                    chunk_hash = hashlib.md5(f.read()).hexdigest()
                if chunk_hash != expected_hash:
                    return False, f"Hash mismatch: expected {expected_hash}, got {chunk_hash}"

            return True, None
        except Exception as e:
            return False, str(e)

    def mark_chunk_uploaded(
        self,
        upload_id: str,
        chunk_number: int,
        chunk_size: int,
        chunk_hash: str
    ) -> None:
        """Mark a chunk as uploaded with metadata."""
        chunk_key = self._get_chunk_key(upload_id, chunk_number)
        metadata = ChunkMetadata(
            number=chunk_number,
            size=chunk_size,
            md5=chunk_hash,
            uploaded_at=datetime.utcnow()
        )
        
        # Store chunk metadata in Redis
        self.redis.hset(
            chunk_key,
            mapping={
                'size': metadata.size,
                'md5': metadata.md5,
                'uploaded_at': metadata.uploaded_at.isoformat(),
                'retry_count': metadata.retry_count
            }
        )
        self.redis.expire(chunk_key, Config.UPLOAD_EXPIRY)

        # Update upload progress
        upload_key = self._get_upload_key(upload_id)
        pipe = self.redis.pipeline()
        pipe.hincrby(upload_key, 'uploaded_chunks', 1)
        pipe.hincrby(upload_key, 'uploaded_bytes', chunk_size)
        pipe.execute()

    def get_chunk_metadata(
        self,
        upload_id: str,
        chunk_number: int
    ) -> Optional[ChunkMetadata]:
        """Get metadata for a specific chunk."""
        chunk_key = self._get_chunk_key(upload_id, chunk_number)
        data = self.redis.hgetall(chunk_key)
        
        if not data:
            return None

        return ChunkMetadata(
            number=chunk_number,
            size=int(data[b'size']),
            md5=data[b'md5'].decode(),
            uploaded_at=datetime.fromisoformat(data[b'uploaded_at'].decode()),
            retry_count=int(data[b'retry_count'])
        )

    def get_upload_progress(
        self,
        upload_id: str,
        total_chunks: int,
        total_size: int
    ) -> Dict[str, Union[int, float, List[int]]]:
        """Get detailed upload progress."""
        upload_key = self._get_upload_key(upload_id)
        data = self.redis.hgetall(upload_key)

        uploaded_chunks = int(data.get(b'uploaded_chunks', 0))
        uploaded_bytes = int(data.get(b'uploaded_bytes', 0))

        # Get list of missing chunks
        all_chunks = set(range(1, total_chunks + 1))
        uploaded_chunk_list = []
        
        for i in all_chunks:
            if self.redis.exists(self._get_chunk_key(upload_id, i)):
                uploaded_chunk_list.append(i)

        missing_chunks = sorted(all_chunks - set(uploaded_chunk_list))

        return {
            'total_chunks': total_chunks,
            'uploaded_chunks': uploaded_chunks,
            'missing_chunks': missing_chunks,
            'total_size': total_size,
            'uploaded_bytes': uploaded_bytes,
            'progress_percent': (uploaded_bytes / total_size * 100) if total_size > 0 else 0
        }

    def cleanup_expired_upload(self, upload_id: str) -> None:
        """Clean up expired upload data and chunks."""
        try:
            # Delete chunk files
            chunk_dir = os.path.join(Config.CHUNKS_DIR, upload_id)
            if os.path.exists(chunk_dir):
                for file in os.listdir(chunk_dir):
                    try:
                        os.remove(os.path.join(chunk_dir, file))
                    except OSError as e:
                        logger.error(f"Error deleting chunk file: {e}")
                try:
                    os.rmdir(chunk_dir)
                except OSError as e:
                    logger.error(f"Error deleting chunk directory: {e}")

            # Delete Redis keys
            keys_to_delete = [
                self._get_upload_key(upload_id),
                *self.redis.keys(f"chunk:{upload_id}:*")
            ]
            if keys_to_delete:
                self.redis.delete(*keys_to_delete)

            logger.info(f"Cleaned up expired upload {upload_id}")
        except Exception as e:
            logger.error(f"Error cleaning up upload {upload_id}: {e}")

    def verify_final_assembly(
        self,
        upload_id: str,
        final_path: str,
        expected_size: int,
        chunk_dir: str
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Verify final assembled file."""
        try:
            # Check if file exists
            if not os.path.exists(final_path):
                return False, None, "Assembled file not found"

            # Verify size
            actual_size = os.path.getsize(final_path)
            if actual_size != expected_size:
                return False, None, f"Size mismatch: expected {expected_size}, got {actual_size}"

            # Calculate file hash
            file_hash = hashlib.sha256()
            with open(final_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    file_hash.update(chunk)
            file_hash = file_hash.hexdigest()

            return True, file_hash, None
        except Exception as e:
            return False, None, str(e)

# Database Models
Base = declarative_base()

class VideoStatus(enum.Enum):
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    QUEUED = "queued"
    TRANSCODING = "transcoding"
    READY = "ready"
    FAILED = "failed"

class Video(Base):
    __tablename__ = 'videos'
    
    id = Column(String(36), primary_key=True)
    title = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    file_hash = Column(String(64), nullable=True)
    mime_type = Column(String(100), nullable=False)
    status = Column(Enum(VideoStatus), default=VideoStatus.UPLOADING)
    upload_method = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    uploaded_at = Column(DateTime, nullable=True)
    transcoded_at = Column(DateTime, nullable=True)
    uploader_id = Column(String(36), nullable=True)
    duration = Column(Integer, nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'filename': self.filename,
            'original_filename': self.original_filename,
            'file_size': self.file_size,
            'file_hash': self.file_hash,
            'mime_type': self.mime_type,
            'status': self.status.value if isinstance(self.status, VideoStatus) else self.status,
            'upload_method': self.upload_method,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
        }

class ChunkedUpload(Base):
    __tablename__ = 'chunked_uploads'
    
    id = Column(String(36), primary_key=True)
    video_id = Column(String(36), nullable=False)
    filename = Column(String(255), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    total_chunks = Column(Integer, nullable=False)
    uploaded_chunks = Column(Integer, default=0)
    is_complete = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    
    def to_dict(self):
        return {
            'upload_id': self.id,
            'video_id': self.video_id,
            'filename': self.filename,
            'file_size': self.file_size,
            'total_chunks': self.total_chunks,
            'uploaded_chunks': self.uploaded_chunks,
            'progress_percent': round((self.uploaded_chunks / self.total_chunks) * 100, 2) if self.total_chunks > 0 else 0,
            'is_complete': self.is_complete,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
        }

class UploadMetrics(Base):
    __tablename__ = 'upload_metrics'
    
    id = Column(String(36), primary_key=True)
    video_id = Column(String(36), nullable=False)
    upload_method = Column(String(50), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    upload_duration = Column(Integer, nullable=False)
    throughput = Column(Integer, nullable=False)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

# Database initialization
engine = create_engine(Config.DATABASE_URL, pool_pre_ping=True)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

# Flask App
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = Config.MAX_UPLOAD_SIZE

# Ensure directories exist
os.makedirs(Config.CHUNKS_DIR, exist_ok=True)
os.makedirs(Config.RAW_DIR, exist_ok=True)

# Redis for chunk tracking
redis_client = redis.from_url(Config.REDIS_URL, decode_responses=True)

# Initialize chunk manager
chunk_manager = ChunkManager(redis_client)

# RabbitMQ Connection
def get_rabbitmq_connection():
    """Create RabbitMQ connection and channel"""
    try:
        params = pika.URLParameters(Config.RABBITMQ_URL)
        connection = pika.BlockingConnection(params)
        channel = connection.channel()
        channel.queue_declare(queue=Config.RABBITMQ_QUEUE, durable=True)
        return connection, channel
    except Exception as e:
        app.logger.error(f"RabbitMQ connection failed: {e}")
        return None, None

def publish_transcode_job(video_data):
    """Publish transcode job to RabbitMQ"""
    try:
        connection, channel = get_rabbitmq_connection()
        if not channel:
            return False
        
        message = json.dumps(video_data)
        channel.basic_publish(
            exchange='',
            routing_key=Config.RABBITMQ_QUEUE,
            body=message,
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type='application/json'
            )
        )
        connection.close()
        app.logger.info(f"Published transcode job for video {video_data['video_id']}")
        return True
    except Exception as e:
        app.logger.error(f"Failed to publish job: {e}")
        return False

def is_chunk_uploaded(upload_id: str, chunk_number: int) -> bool:
    """Check if a chunk has been uploaded."""
    metadata = chunk_manager.get_chunk_metadata(upload_id, chunk_number)
    return metadata is not None

def get_uploaded_chunks(upload_id: str, total_chunks: int) -> List[int]:
    """Get list of uploaded chunk numbers."""
    uploaded = []
    for i in range(1, total_chunks + 1):
        if is_chunk_uploaded(upload_id, i):
            uploaded.append(i)
    return uploaded

def cleanup_upload(upload_id: str) -> None:
    """Clean up chunks after successful upload."""
    try:
        # Remove chunk files
        chunk_dir = os.path.join(Config.CHUNKS_DIR, upload_id)
        if os.path.exists(chunk_dir):
            for file in os.listdir(chunk_dir):
                try:
                    os.remove(os.path.join(chunk_dir, file))
                except OSError as e:
                    logger.error(f"Error deleting chunk file: {e}")
            try:
                os.rmdir(chunk_dir)
            except OSError as e:
                logger.error(f"Error deleting chunk directory: {e}")

        # Remove Redis keys
        keys_to_delete = [
            f"upload:{upload_id}",
            *redis_client.keys(f"chunk:{upload_id}:*")
        ]
        if keys_to_delete:
            redis_client.delete(*keys_to_delete)

        logger.info(f"Cleaned up upload {upload_id}")
    except Exception as e:
        logger.error(f"Error cleaning up upload {upload_id}: {e}")

def calculate_file_hash(filepath: str) -> str:
    """Calculate SHA-256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        # Read file in chunks to handle large files
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def allowed_file(filename: str) -> bool:
    """Check if file has allowed extension and valid name."""
    if not filename or '.' not in filename:
        return False
    
    if len(filename) > Config.MAX_FILENAME_LENGTH:
        return False

    ext = filename.rsplit('.', 1)[1].lower()
    return ext in Config.ALLOWED_EXTENSIONS

def validate_mime_type(mime_type: str) -> bool:
    """Check if MIME type is allowed."""
    return mime_type in Config.ALLOWED_MIME_TYPES

def calculate_chunk_hash(chunk_data: bytes) -> str:
    """Calculate MD5 hash of chunk data."""
    return hashlib.md5(chunk_data).hexdigest()

def validate_chunk_size(chunk_size: int) -> Tuple[bool, Optional[str]]:
    """Validate chunk size is within allowed range."""
    if chunk_size < Config.MIN_CHUNK_SIZE:
        return False, f"Chunk size too small. Minimum: {Config.MIN_CHUNK_SIZE} bytes"
    if chunk_size > Config.MAX_CHUNK_SIZE:
        return False, f"Chunk size too large. Maximum: {Config.MAX_CHUNK_SIZE} bytes"
    return True, None

def rate_limit_check(
    ip: str,
    upload_id: Optional[str] = None,
    is_new_upload: bool = False
) -> Tuple[bool, Optional[str], int]:
    """Check rate limits for uploads and chunks."""
    if not Config.RATE_LIMIT_ENABLED:
        return True, None, -1

    window = Config.RATE_LIMIT_WINDOW
    upload_key = f"ratelimit:uploads:{ip}"
    chunk_key = f"ratelimit:chunks:{ip}"

    pipe = redis_client.pipeline()
    now = time.time()
    window_start = now - window

    if is_new_upload:
        # Check upload count
        pipe.zremrangebyscore(upload_key, 0, window_start)
        pipe.zcard(upload_key)
        pipe.zadd(upload_key, {str(now): now})
        pipe.expire(upload_key, window)
        
        _, upload_count, *_ = pipe.execute()
        
        if upload_count >= Config.RATE_LIMIT_MAX_UPLOADS:
            reset_in = int(window - (now - float(redis_client.zrange(upload_key, 0, 0)[0])))
            return False, "Upload rate limit exceeded", reset_in
    
    else:
        # Check chunk upload count
        pipe.zremrangebyscore(chunk_key, 0, window_start)
        pipe.zcard(chunk_key)
        pipe.zadd(chunk_key, {str(now): now})
        pipe.expire(chunk_key, window)
        
        _, chunk_count, *_ = pipe.execute()
        
        if chunk_count >= Config.RATE_LIMIT_MAX_CHUNKS:
            reset_in = int(window - (now - float(redis_client.zrange(chunk_key, 0, 0)[0])))
            return False, "Chunk upload rate limit exceeded", reset_in

    return True, None, -1

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'chunked-upload',
        'timestamp': datetime.utcnow().isoformat()
    }), 200

@app.route('/api/v1/upload/init', methods=['POST'])
def initialize_upload():
    """
    Initialize chunked upload
    Body: {
        "filename": "video.mp4",
        "file_size": 104857600,
        "total_chunks": 100,
        "mime_type": "video/mp4",
        "uploader_id": "user123"
    }
    """
    try:
        data = request.get_json()
        
        # Validate input
        if not data or 'filename' not in data or 'file_size' not in data or 'total_chunks' not in data:
            return jsonify({'error': 'Missing required fields'}), 400
        
        filename = secure_filename(data['filename'])
        if not allowed_file(filename):
            return jsonify({
                'error': 'Invalid file type',
                'allowed_types': list(Config.ALLOWED_EXTENSIONS)
            }), 400
        
        file_size = int(data['file_size'])
        total_chunks = int(data['total_chunks'])
        
        if file_size > Config.MAX_UPLOAD_SIZE:
            return jsonify({'error': 'File too large'}), 413
        
        if total_chunks <= 0 or total_chunks > 10000:
            return jsonify({'error': 'Invalid chunk count'}), 400
        
        # Generate IDs
        upload_id = str(uuid.uuid4())
        video_id = str(uuid.uuid4())
        
        # Create database session
        db = SessionLocal()
        
        # Create video record
        video = Video(
            id=video_id,
            title=data.get('title', 'Untitled Video'),
            filename=f"{video_id}.{filename.rsplit('.', 1)[1]}",
            original_filename=filename,
            file_size=file_size,
            mime_type=data.get('mime_type', 'video/mp4'),
            status=VideoStatus.UPLOADING,
            upload_method='chunked',
            uploader_id=data.get('uploader_id', 'anonymous')
        )
        db.add(video)
        
        # Create chunked upload record
        chunked_upload = ChunkedUpload(
            id=upload_id,
            video_id=video_id,
            filename=filename,
            file_size=file_size,
            total_chunks=total_chunks,
            uploaded_chunks=0,
            is_complete=False,
            expires_at=datetime.utcnow() + timedelta(seconds=Config.UPLOAD_EXPIRY)
        )
        db.add(chunked_upload)
        db.commit()
        
        # Create chunks directory
        chunk_dir = os.path.join(Config.CHUNKS_DIR, upload_id)
        os.makedirs(chunk_dir, exist_ok=True)
        
        response_data = chunked_upload.to_dict()
        db.close()
        
        app.logger.info(f"Initialized chunked upload {upload_id} for video {video_id}")
        
        return jsonify({
            'success': True,
            'message': 'Upload initialized',
            'data': response_data
        }), 201
        
    except Exception as e:
        app.logger.error(f"Upload initialization failed: {str(e)}")
        try:
            db.rollback()
            db.close()
        except:
            pass
        return jsonify({'error': 'Initialization failed', 'details': str(e)}), 500

@app.route('/api/v1/upload/chunk', methods=['POST'])
def upload_chunk():
    """
    Upload a single chunk
    Form Data:
        - upload_id: string
        - chunk_number: integer
        - chunk: file
    """
    try:
        # Validate input
        if 'chunk' not in request.files:
            return jsonify({'error': 'No chunk file provided'}), 400
        
        upload_id = request.form.get('upload_id')
        chunk_number = request.form.get('chunk_number')
        
        if not upload_id or not chunk_number:
            return jsonify({'error': 'Missing upload_id or chunk_number'}), 400
        
        chunk_number = int(chunk_number)
        chunk_file = request.files['chunk']
        
        # Get upload record
        db = SessionLocal()
        upload = db.query(ChunkedUpload).filter(ChunkedUpload.id == upload_id).first()
        
        if not upload:
            db.close()
            return jsonify({'error': 'Upload not found'}), 404
        
        if upload.is_complete:
            db.close()
            return jsonify({'error': 'Upload already completed'}), 400
        
        if chunk_number < 1 or chunk_number > upload.total_chunks:
            db.close()
            return jsonify({'error': 'Invalid chunk number'}), 400
        
        # Check if chunk already uploaded
        if is_chunk_uploaded(upload_id, chunk_number):
            db.close()
            return jsonify({
                'success': True,
                'message': 'Chunk already uploaded',
                'chunk_number': chunk_number,
                'duplicate': True
            }), 200
        
        # Save chunk
        chunk_dir = os.path.join(Config.CHUNKS_DIR, upload_id)
        chunk_path = os.path.join(chunk_dir, f"chunk_{chunk_number:06d}")
        chunk_file.save(chunk_path)
        
        # Calculate chunk hash and mark as uploaded
        chunk_size = os.path.getsize(chunk_path)
        with open(chunk_path, 'rb') as f:
            chunk_hash = calculate_chunk_hash(f.read())
        
        # Mark chunk as uploaded with ChunkManager
        chunk_manager.mark_chunk_uploaded(upload_id, chunk_number, chunk_size, chunk_hash)
        
        # Update uploaded chunks count
        uploaded_chunks = get_uploaded_chunks(upload_id, upload.total_chunks)
        upload.uploaded_chunks = len(uploaded_chunks)
        db.commit()
        db.close()
        
        app.logger.info(f"Uploaded chunk {chunk_number}/{upload.total_chunks} for upload {upload_id}")
        
        return jsonify({
            'success': True,
            'message': 'Chunk uploaded',
            'chunk_number': chunk_number,
            'uploaded_chunks': upload.uploaded_chunks,
            'total_chunks': upload.total_chunks,
            'progress_percent': round((upload.uploaded_chunks / upload.total_chunks) * 100, 2)
        }), 200
        
    except Exception as e:
        app.logger.error(f"Chunk upload failed: {str(e)}")
        return jsonify({'error': 'Chunk upload failed', 'details': str(e)}), 500

@app.route('/api/v1/upload/complete', methods=['POST'])
def complete_upload():
    """
    Complete chunked upload and assemble file
    Body: {
        "upload_id": "...",
        "title": "My Video"
    }
    """
    start_time = time.time()
    
    try:
        data = request.get_json()
        upload_id = data.get('upload_id')
        
        if not upload_id:
            return jsonify({'error': 'Missing upload_id'}), 400
        
        # Get upload record
        db = SessionLocal()
        upload = db.query(ChunkedUpload).filter(ChunkedUpload.id == upload_id).first()
        
        if not upload:
            db.close()
            return jsonify({'error': 'Upload not found'}), 404
        
        if upload.is_complete:
            db.close()
            return jsonify({'error': 'Upload already completed'}), 400
        
        # Verify all chunks are uploaded
        uploaded_chunks = get_uploaded_chunks(upload_id, upload.total_chunks)
        if len(uploaded_chunks) != upload.total_chunks:
            missing = set(range(1, upload.total_chunks + 1)) - set(uploaded_chunks)
            db.close()
            return jsonify({
                'error': 'Missing chunks',
                'missing_chunks': sorted(list(missing))[:10],  # Show first 10
                'missing_count': len(missing)
            }), 400
        
        # Assemble file
        video = db.query(Video).filter(Video.id == upload.video_id).first()
        final_path = os.path.join(Config.RAW_DIR, video.filename)
        chunk_dir = os.path.join(Config.CHUNKS_DIR, upload_id)
        
        app.logger.info(f"Assembling {upload.total_chunks} chunks for upload {upload_id}")
        
        with open(final_path, 'wb') as outfile:
            for i in range(1, upload.total_chunks + 1):
                chunk_path = os.path.join(chunk_dir, f"chunk_{i:06d}")
                if not os.path.exists(chunk_path):
                    raise Exception(f"Chunk {i} missing during assembly")
                
                with open(chunk_path, 'rb') as infile:
                    outfile.write(infile.read())
        
        # Verify file size
        actual_size = os.path.getsize(final_path)
        if actual_size != upload.file_size:
            os.remove(final_path)
            raise Exception(f"File size mismatch: expected {upload.file_size}, got {actual_size}")
        
        # Calculate hash
        file_hash = calculate_file_hash(final_path)
        
        # Update records
        video.file_hash = file_hash
        video.status = VideoStatus.UPLOADED
        video.uploaded_at = datetime.utcnow()
        if 'title' in data:
            video.title = data['title']
        
        upload.is_complete = True
        upload.completed_at = datetime.utcnow()
        
        db.commit()
        
        # Calculate metrics
        upload_duration = int((time.time() - start_time) * 1000)
        throughput = int(upload.file_size / (time.time() - start_time)) if (time.time() - start_time) > 0 else 0
        
        metrics = UploadMetrics(
            id=str(uuid.uuid4()),
            video_id=upload.video_id,
            upload_method='chunked',
            file_size=upload.file_size,
            upload_duration=upload_duration,
            throughput=throughput,
            retry_count=0  # Could track retries if implemented
        )
        db.add(metrics)
        db.commit()
        
        # Publish to transcode queue
        job_data = {
            'video_id': video.id,
            'filename': video.filename,
            'filepath': final_path,
            'original_filename': video.original_filename,
            'file_size': video.file_size,
            'upload_method': 'chunked'
        }
        
        if publish_transcode_job(job_data):
            video.status = VideoStatus.QUEUED
            db.commit()
        
        response_data = video.to_dict()
        response_data['upload_duration_ms'] = upload_duration
        response_data['throughput_bps'] = throughput
        
        db.close()
        
        # Cleanup chunks
        cleanup_upload(upload_id)
        
        app.logger.info(f"Completed upload {upload_id} in {upload_duration}ms")
        
        return jsonify({
            'success': True,
            'message': 'Upload completed successfully',
            'data': response_data
        }), 200
        
    except Exception as e:
        app.logger.error(f"Upload completion failed: {str(e)}")
        try:
            db.rollback()
            db.close()
        except:
            pass
        return jsonify({'error': 'Upload completion failed', 'details': str(e)}), 500

@app.route('/api/v1/upload/<upload_id>/status', methods=['GET'])
def get_upload_status(upload_id):
    """Get upload status and missing chunks for resume"""
    try:
        db = SessionLocal()
        upload = db.query(ChunkedUpload).filter(ChunkedUpload.id == upload_id).first()
        
        if not upload:
            db.close()
            return jsonify({'error': 'Upload not found'}), 404
        
        # Get uploaded chunks
        uploaded_chunks = get_uploaded_chunks(upload_id, upload.total_chunks)
        missing_chunks = sorted(set(range(1, upload.total_chunks + 1)) - set(uploaded_chunks))
        
        response_data = upload.to_dict()
        response_data['uploaded_chunk_list'] = uploaded_chunks[:100]  # Limit response size
        response_data['missing_chunk_list'] = missing_chunks[:100]
        response_data['missing_count'] = len(missing_chunks)
        
        db.close()
        
        return jsonify({
            'success': True,
            'data': response_data
        }), 200
        
    except Exception as e:
        app.logger.error(f"Error getting upload status: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/v1/videos/<video_id>', methods=['GET'])
def get_video_status(video_id):
    """Get video status"""
    try:
        db = SessionLocal()
        video = db.query(Video).filter(Video.id == video_id).first()
        
        if not video:
            db.close()
            return jsonify({'error': 'Video not found'}), 404
        
        data = video.to_dict()
        db.close()
        
        return jsonify({'success': True, 'data': data}), 200
        
    except Exception as e:
        app.logger.error(f"Error fetching video: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/v1/metrics', methods=['GET'])
def get_metrics():
    """Get upload metrics for analysis"""
    try:
        db = SessionLocal()
        metrics = db.query(UploadMetrics).filter(
            UploadMetrics.upload_method == 'chunked'
        ).order_by(UploadMetrics.created_at.desc()).limit(100).all()
        
        data = [{
            'video_id': m.video_id,
            'file_size': m.file_size,
            'upload_duration_ms': m.upload_duration,
            'throughput_bps': m.throughput,
            'retry_count': m.retry_count,
            'created_at': m.created_at.isoformat()
        } for m in metrics]
        
        if data:
            avg_duration = sum(m['upload_duration_ms'] for m in data) / len(data)
            avg_throughput = sum(m['throughput_bps'] for m in data) / len(data)
        else:
            avg_duration = 0
            avg_throughput = 0
        
        db.close()
        
        return jsonify({
            'success': True,
            'count': len(data),
            'averages': {
                'upload_duration_ms': avg_duration,
                'throughput_bps': avg_throughput
            },
            'data': data
        }), 200
        
    except Exception as e:
        app.logger.error(f"Error fetching metrics: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8002, debug=True)