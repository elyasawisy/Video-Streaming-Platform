"""
Chunked Upload Service with Resumability
Handles large video uploads in chunks with ability to resume on failure
"""
import os
import uuid
import hashlib
import time
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import pika
import redis
from sqlalchemy import create_engine, Column, String, Integer, DateTime, BigInteger, Enum, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import enum

# Configuration
class Config:
    DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://videouser:videopass@localhost:5432/video_streaming')
    RABBITMQ_URL = os.getenv('RABBITMQ_URL', 'amqp://guest:guest@localhost:5672/')
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
    UPLOAD_DIR = os.getenv('UPLOAD_DIR', './uploads')
    CHUNKS_DIR = os.path.join(UPLOAD_DIR, 'chunks')
    RAW_DIR = os.path.join(UPLOAD_DIR, 'raw')
    MAX_UPLOAD_SIZE = int(os.getenv('MAX_UPLOAD_SIZE', 2 * 1024 * 1024 * 1024))  # 2GB
    CHUNK_SIZE = 1024 * 1024  # 1MB per chunk
    ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'flv', 'wmv'}
    RABBITMQ_QUEUE = 'transcode_queue'
    UPLOAD_EXPIRY = 24 * 3600  # 24 hours

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

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

def calculate_file_hash(filepath):
    """Calculate SHA256 hash of file"""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def get_chunk_key(upload_id, chunk_number):
    """Generate Redis key for chunk tracking"""
    return f"chunk:{upload_id}:{chunk_number}"

def mark_chunk_uploaded(upload_id, chunk_number):
    """Mark a chunk as uploaded in Redis"""
    key = get_chunk_key(upload_id, chunk_number)
    redis_client.setex(key, Config.UPLOAD_EXPIRY, "1")

def is_chunk_uploaded(upload_id, chunk_number):
    """Check if chunk is already uploaded"""
    key = get_chunk_key(upload_id, chunk_number)
    return redis_client.exists(key)

def get_uploaded_chunks(upload_id, total_chunks):
    """Get list of uploaded chunk numbers"""
    uploaded = []
    for i in range(1, total_chunks + 1):
        if is_chunk_uploaded(upload_id, i):
            uploaded.append(i)
    return uploaded

def cleanup_upload(upload_id):
    """Clean up chunks and Redis keys for an upload"""
    # Delete chunks directory
    chunk_dir = os.path.join(Config.CHUNKS_DIR, upload_id)
    if os.path.exists(chunk_dir):
        for file in os.listdir(chunk_dir):
            os.remove(os.path.join(chunk_dir, file))
        os.rmdir(chunk_dir)
    
    # Delete Redis keys
    pattern = f"chunk:{upload_id}:*"
    for key in redis_client.scan_iter(match=pattern):
        redis_client.delete(key)

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
        
        # Mark chunk as uploaded
        mark_chunk_uploaded(upload_id, chunk_number)
        
        # Update uploaded chunks count
        upload.uploaded_chunks = len(get_uploaded_chunks(upload_id, upload.total_chunks))
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