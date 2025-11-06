"""
gRPC Server for Video Service with resilience patterns
Handles inter-service communication using gRPC
"""

import grpc
from concurrent import futures
import time
import os
import sys
import logging
from datetime import datetime
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine.base import Connection
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
import prometheus_client as prom
from grpc_health.v1 import health_pb2_grpc
from grpc_health.v1 import health
from grpc_health.v1 import health_pb2

# Add gRPC directory to path for direct execution
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

# Import generated protobuf code
import video_pb2
import video_pb2_grpc

# Import database models
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from upload_service.models import Video, VideoStatus, Base

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://videouser:videopass@localhost:5432/video_streaming')
GRPC_HOST = os.getenv('GRPC_HOST', '127.0.0.1')  # Default to localhost IPv4
GRPC_PORT = int(os.getenv('GRPC_PORT', '50051'))
UPLOAD_DIR = os.getenv('UPLOAD_DIR', './uploads')
MAX_WORKERS = int(os.getenv('GRPC_MAX_WORKERS', '10'))
MAX_MESSAGE_LENGTH = int(os.getenv('GRPC_MAX_MESSAGE_LENGTH', 100 * 1024 * 1024))  # 100MB

def is_port_in_use(port, host='127.0.0.1'):
    """Check if a port is in use"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except socket.error:
            return True

# Prometheus metrics
GRPC_REQUESTS = prom.Counter(
    'grpc_video_service_requests_total',
    'Total gRPC requests',
    ['method', 'status']
)
GRPC_LATENCY = prom.Histogram(
    'grpc_video_service_latency_seconds',
    'gRPC request latency',
    ['method']
)
DB_ERRORS = prom.Counter(
    'grpc_video_service_db_errors_total',
    'Database errors in gRPC service'
)
VIDEO_STATES = prom.Gauge(
    'video_service_states',
    'Number of videos in each state',
    ['state']
)

# Database setup with connection pooling
engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True
)
SessionLocal = sessionmaker(bind=engine)

# Database connection health check
@event.listens_for(engine, "engine_connect")
def ping_connection(connection):
    """Check database connection health"""
    if not connection.closed and not connection.invalidated:
        try:
            # Execute simple SELECT 1 query to check connection
            with connection.begin() as trans:
                connection.scalar(select(1))
                trans.commit()
        except SQLAlchemyError as e:
            # If connection is invalid, attempt to reconnect
            logger.error(f"Database connection error: {e}")
            DB_ERRORS.inc()
            if connection.invalidated:
                connection.scalar(select(1))
            else:
                raise

class DatabaseManager:
    """Database session context manager with retries"""
    
    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type(SQLAlchemyError)
    )
    def get_session():
        """Get database session with retry logic"""
        try:
            db = SessionLocal()
            return db
        except SQLAlchemyError as e:
            logger.error(f"Database connection error: {e}")
            DB_ERRORS.inc()
            raise
    
    @staticmethod
    def safe_commit(db):
        """Safely commit database changes"""
        try:
            db.commit()
        except SQLAlchemyError as e:
            logger.error(f"Database commit error: {e}")
            DB_ERRORS.inc()
            db.rollback()
            raise
        finally:
            db.close()

class GrpcErrorHandler:
    """Error handling decorator for gRPC methods"""
    
    @staticmethod
    def handle_errors(method):
        def wrapper(self, request, context):
            start_time = time.time()
            try:
                result = method(self, request, context)
                GRPC_REQUESTS.labels(
                    method=method.__name__,
                    status="success"
                ).inc()
                return result
                
            except grpc.RpcError as e:
                GRPC_REQUESTS.labels(
                    method=method.__name__,
                    status="error"
                ).inc()
                logger.error(f"gRPC error in {method.__name__}: {e}")
                context.set_code(e.code())
                context.set_details(e.details())
                return None
                
            except SQLAlchemyError as e:
                GRPC_REQUESTS.labels(
                    method=method.__name__,
                    status="db_error"
                ).inc()
                logger.error(f"Database error in {method.__name__}: {e}")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("Database error occurred")
                return None
                
            except Exception as e:
                GRPC_REQUESTS.labels(
                    method=method.__name__,
                    status="error"
                ).inc()
                logger.error(f"Unexpected error in {method.__name__}: {e}")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(str(e))
                return None
                
            finally:
                duration = time.time() - start_time
                GRPC_LATENCY.labels(
                    method=method.__name__
                ).observe(duration)
        
        return wrapper

class VideoServiceServicer(video_pb2_grpc.VideoServiceServicer):
    """Implements the VideoService gRPC service with resilience patterns"""
    
    @GrpcErrorHandler.handle_errors
    def GetVideo(self, request, context):
        """Get video information by ID"""
        db = DatabaseManager.get_session()
        
        video = db.query(Video).filter(Video.id == request.video_id).first()
        
        if not video:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f'Video {request.video_id} not found')
            return video_pb2.VideoResponse()
        
        response = video_pb2.VideoResponse(
            video_id=video.id,
            title=video.title,
            filename=video.filename,
            file_size=video.file_size,
            status=video.status.value if isinstance(video.status, VideoStatus) else video.status,
            mime_type=video.mime_type,
            created_at=video.created_at.isoformat() if video.created_at else '',
            metadata={
                'original_filename': video.original_filename,
                'upload_method': video.upload_method,
                'file_hash': video.file_hash or ''
            }
        )
        
        db.close()
        logger.info(f"Retrieved video info for {request.video_id}")
        return response
    
    @GrpcErrorHandler.handle_errors
    def UpdateVideoStatus(self, request, context):
        """Update video processing status"""
        db = DatabaseManager.get_session()
        
        video = db.query(Video).filter(Video.id == request.video_id).first()
        
        if not video:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f'Video {request.video_id} not found')
            return video_pb2.StatusResponse(success=False, message='Video not found')
        
        # Update status
        if request.status == 'transcoding':
            video.status = VideoStatus.TRANSCODING
        elif request.status == 'ready':
            video.status = VideoStatus.READY
            video.transcoded_at = datetime.utcnow()
        elif request.status == 'failed':
            video.status = VideoStatus.FAILED
        
        DatabaseManager.safe_commit(db)
        
        # Update metrics
        for state in VideoStatus:
            count = db.query(Video).filter(Video.status == state).count()
            VIDEO_STATES.labels(state=state.name).set(count)
        
        logger.info(f"Updated video {request.video_id} status to {request.status}")
        
        return video_pb2.StatusResponse(
            success=True,
            message=f"Status updated to {request.status}",
            timestamp=datetime.utcnow().isoformat()
        )
    
    @GrpcErrorHandler.handle_errors
    def GetVideoChunks(self, request, context):
        """Stream video chunks for playback"""
        # Determine file path based on quality
        base_path = os.path.join(UPLOAD_DIR, 'transcoded', request.video_id)
        
        # For original quality, use raw file
        if request.quality == 'original':
            db = DatabaseManager.get_session()
            video = db.query(Video).filter(Video.id == request.video_id).first()
            if video:
                filepath = os.path.join(UPLOAD_DIR, 'raw', video.filename)
            else:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                return
            db.close()
        else:
            # Use transcoded file
            filepath = os.path.join(base_path, f"{request.quality}.mp4")
        
        if not os.path.exists(filepath):
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f'Video file not found: {filepath}')
            return
        
        # Stream file in chunks with backpressure handling
        chunk_size = request.chunk_size if request.chunk_size > 0 else 64 * 1024  # 64KB default
        offset = request.offset
        
        try:
            with open(filepath, 'rb') as f:
                f.seek(offset)
                
                while True:
                    chunk_data = f.read(chunk_size)
                    if not chunk_data:
                        break
                    
                    is_last = len(chunk_data) < chunk_size
                    
                    # Handle backpressure
                    try:
                        yield video_pb2.VideoChunk(
                            data=chunk_data,
                            offset=offset,
                            size=len(chunk_data),
                            is_last=is_last
                        )
                    except grpc.RpcError as e:
                        if e.code() == grpc.StatusCode.CANCELLED:
                            logger.info("Client cancelled streaming")
                            return
                        raise
                    
                    offset += len(chunk_data)
                    
                    if is_last:
                        break
            
            logger.info(f"Streamed video {request.video_id} ({request.quality}) from offset {request.offset}")
            
        except OSError as e:
            logger.error(f"File streaming error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
    
    @GrpcErrorHandler.handle_errors
    def ReportTranscodeProgress(self, request, context):
        """Receive transcoding progress updates from workers"""
        logger.info(
            f"Transcode progress: Video {request.video_id} - "
            f"{request.progress_percent}% ({request.current_quality}) "
            f"by worker {request.worker_id}"
        )
        
        return video_pb2.StatusResponse(
            success=True,
            message="Progress recorded",
            timestamp=datetime.utcnow().isoformat()
        )
    
    @GrpcErrorHandler.handle_errors
    def GetQueueStatus(self, request, context):
        """Get status of transcoding queue"""
        db = DatabaseManager.get_session()
        
        try:
            # Count videos in different states
            queued = db.query(Video).filter(Video.status == VideoStatus.QUEUED).count()
            transcoding = db.query(Video).filter(Video.status == VideoStatus.TRANSCODING).count()
            
            # Get list of queued video IDs
            queued_videos = db.query(Video.id).filter(
                Video.status == VideoStatus.QUEUED
            ).limit(10).all()
            
            video_ids = [v.id for v in queued_videos]
            
            # Update metrics
            VIDEO_STATES.labels(state='QUEUED').set(queued)
            VIDEO_STATES.labels(state='TRANSCODING').set(transcoding)
            
            return video_pb2.QueueStatusResponse(
                pending_jobs=queued,
                active_workers=transcoding,
                video_ids=video_ids
            )
            
        finally:
            db.close()

def initialize_health_checks(health_servicer: health.HealthServicer):
    """Initialize health checks for gRPC services"""
    # Set initial status for services
    health_servicer.set(
        'video.VideoService', 
        health_pb2.HealthCheckResponse.ServingStatus.SERVING
    )
    health_servicer.set(
        '', # Overall health
        health_pb2.HealthCheckResponse.ServingStatus.SERVING
    )
    
    # Update database health
    try:
        db = DatabaseManager.get_session()
        db.scalar(select(1))
        db.close()
        health_servicer.set(
            'database',
            health_pb2.HealthCheckResponse.ServingStatus.SERVING
        )
    except SQLAlchemyError:
        health_servicer.set(
            'database',
            health_pb2_grpc.HealthCheckResponse.ServingStatus.NOT_SERVING
        )

def serve():
    """Start the gRPC server with metrics and health checking"""
    global GRPC_PORT
    
    # Check if primary port is available
    if is_port_in_use(GRPC_PORT, GRPC_HOST):
        logger.error(f"Port {GRPC_PORT} is already in use on {GRPC_HOST}")
        # Try to find an available port
        for port in range(GRPC_PORT + 1, GRPC_PORT + 10):
            if not is_port_in_use(port, GRPC_HOST):
                logger.info(f"Found available port: {port}")
                GRPC_PORT = port
                break
        else:
            logger.error(f"No available ports found in range {GRPC_PORT}-{GRPC_PORT + 9}")
            return

    # Start Prometheus metrics server on next available port
    for metrics_port in range(8000, 8010):
        if not is_port_in_use(metrics_port):
            try:
                prom.start_http_server(metrics_port)
                logger.info(f"Metrics server started on port {metrics_port}")
                break
            except Exception as e:
                logger.warning(f"Failed to start metrics server on port {metrics_port}: {e}")
                continue
    
    # Configure server with interceptors and options
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=MAX_WORKERS),
        options=[
            ('grpc.max_send_message_length', MAX_MESSAGE_LENGTH),
            ('grpc.max_receive_message_length', MAX_MESSAGE_LENGTH),
            ('grpc.keepalive_time_ms', 30000),
            ('grpc.keepalive_timeout_ms', 10000),
            ('grpc.http2.min_ping_interval_without_data_ms', 5000),
            ('grpc.http2.max_pings_without_data', 2),
            ('grpc.keepalive_permit_without_calls', 1)
        ]
    )
    
    # Add main service
    video_pb2_grpc.add_VideoServiceServicer_to_server(VideoServiceServicer(), server)
    
    # Add and initialize health checking
    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    initialize_health_checks(health_servicer)
    
    # Start server
    server_address = f"{GRPC_HOST}:{GRPC_PORT}"
    try:
        server.add_insecure_port(server_address)
        server.start()
        logger.info(f"gRPC server started on {server_address}")
    except Exception as e:
        logger.error(f"Failed to start server on {server_address}: {e}")
        return

    server.start()
    
    logger.info(f"gRPC server started on {port}")
    logger.info(f"Metrics available on :8000/metrics")
    
    try:
        while True:
            time.sleep(86400)  # Keep running
    except KeyboardInterrupt:
        logger.info("Shutting down gRPC server...")
        server.stop(0)


if __name__ == '__main__':
    serve()