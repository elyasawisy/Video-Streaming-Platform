"""
gRPC Server for Video Service
Handles inter-service communication using gRPC
"""

import grpc
from concurrent import futures
import time
import os
import logging
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import generated protobuf code
from . import video_pb2
from . import video_pb2_grpc

# Import database models (same as HTTP/2 service)
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from upload_service.models import Video, VideoStatus, Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://videouser:videopass@localhost:5432/video_streaming')
GRPC_PORT = os.getenv('GRPC_PORT', '50051')
UPLOAD_DIR = os.getenv('UPLOAD_DIR', './uploads')

# Database setup
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


class VideoServiceServicer(video_pb2_grpc.VideoServiceServicer):
    """Implements the VideoService gRPC service"""
    
    def GetVideo(self, request, context):
        """Get video information by ID"""
        try:
            db = SessionLocal()
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
            
        except Exception as e:
            logger.error(f"Error getting video: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return video_pb2.VideoResponse()
    
    def UpdateVideoStatus(self, request, context):
        """Update video processing status"""
        try:
            db = SessionLocal()
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
            
            db.commit()
            db.close()
            
            logger.info(f"Updated video {request.video_id} status to {request.status}")
            
            return video_pb2.StatusResponse(
                success=True,
                message=f"Status updated to {request.status}",
                timestamp=datetime.utcnow().isoformat()
            )
            
        except Exception as e:
            logger.error(f"Error updating status: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return video_pb2.StatusResponse(success=False, message=str(e))
    
    def GetVideoChunks(self, request, context):
        """Stream video chunks for playback"""
        try:
            # Determine file path based on quality
            base_path = os.path.join(UPLOAD_DIR, 'transcoded', request.video_id)
            
            # For original quality, use raw file
            if request.quality == 'original':
                db = SessionLocal()
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
            
            # Stream file in chunks
            chunk_size = request.chunk_size if request.chunk_size > 0 else 64 * 1024  # 64KB default
            offset = request.offset
            
            with open(filepath, 'rb') as f:
                f.seek(offset)
                
                while True:
                    chunk_data = f.read(chunk_size)
                    if not chunk_data:
                        break
                    
                    is_last = len(chunk_data) < chunk_size
                    
                    yield video_pb2.VideoChunk(
                        data=chunk_data,
                        offset=offset,
                        size=len(chunk_data),
                        is_last=is_last
                    )
                    
                    offset += len(chunk_data)
                    
                    if is_last:
                        break
            
            logger.info(f"Streamed video {request.video_id} ({request.quality}) from offset {request.offset}")
            
        except Exception as e:
            logger.error(f"Error streaming chunks: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
    
    def ReportTranscodeProgress(self, request, context):
        """Receive transcoding progress updates from workers"""
        try:
            logger.info(
                f"Transcode progress: Video {request.video_id} - "
                f"{request.progress_percent}% ({request.current_quality}) "
                f"by worker {request.worker_id}"
            )
            
            # You could store this in a separate progress table or cache
            # For now, just log it
            
            return video_pb2.StatusResponse(
                success=True,
                message="Progress recorded",
                timestamp=datetime.utcnow().isoformat()
            )
            
        except Exception as e:
            logger.error(f"Error recording progress: {e}")
            return video_pb2.StatusResponse(success=False, message=str(e))
    
    def GetQueueStatus(self, request, context):
        """Get status of transcoding queue"""
        try:
            db = SessionLocal()
            
            # Count videos in different states
            queued = db.query(Video).filter(Video.status == VideoStatus.QUEUED).count()
            transcoding = db.query(Video).filter(Video.status == VideoStatus.TRANSCODING).count()
            
            # Get list of queued video IDs
            queued_videos = db.query(Video.id).filter(
                Video.status == VideoStatus.QUEUED
            ).limit(10).all()
            
            video_ids = [v.id for v in queued_videos]
            
            db.close()
            
            return video_pb2.QueueStatusResponse(
                pending_jobs=queued,
                active_workers=transcoding,  # Approximate based on transcoding count
                video_ids=video_ids
            )
            
        except Exception as e:
            logger.error(f"Error getting queue status: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            return video_pb2.QueueStatusResponse()


def serve():
    """Start the gRPC server"""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    video_pb2_grpc.add_VideoServiceServicer_to_server(VideoServiceServicer(), server)
    server.add_insecure_port(f'[::]:{GRPC_PORT}')
    server.start()
    
    logger.info(f"gRPC server started on port {GRPC_PORT}")
    
    try:
        while True:
            time.sleep(86400)  # Keep running
    except KeyboardInterrupt:
        logger.info("Shutting down gRPC server...")
        server.stop(0)


if __name__ == '__main__':
    serve()