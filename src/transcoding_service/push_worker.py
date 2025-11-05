"""
Push-Based Transcoding Worker
Subscribes to RabbitMQ exchange and receives jobs via pub-sub
"""

import os
import sys
import json
import time
import uuid
import logging
from datetime import datetime
import pika
import grpc
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from transcoding_service.transcoder import VideoTranscoder
from transcoding_service.config import Config as BaseConfig
from upload_service.models import Video, VideoStatus, Base as UploadBase

# gRPC imports (generated files need to exist; fall back gracefully if not)
try:
    from grpc_services import video_pb2, video_pb2_grpc
except Exception:
    video_pb2 = None
    video_pb2_grpc = None


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Config(BaseConfig):
    """Push worker specific configuration (extends transcoding_service.config.Config)"""
    RABBITMQ_EXCHANGE = os.getenv('RABBITMQ_EXCHANGE', 'video_events')
    RABBITMQ_ROUTING_KEY = os.getenv('RABBITMQ_ROUTING_KEY', 'video.transcode')
    # Optional compatibility with queue-based publishing
    RABBITMQ_COMPAT_QUEUE = os.getenv('RABBITMQ_COMPAT_QUEUE', 'transcode_queue')


# Database setup
engine = create_engine(Config.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


class PushWorker:
    """Push-based worker that subscribes to RabbitMQ exchange"""

    def __init__(self):
        self.worker_id = os.getenv('WORKER_ID', f"push-worker-{uuid.uuid4().hex[:8]}")
        self.connection = None
        self.channel = None
        self.queue_name = None  # Dynamic queue name
        self.grpc_channel = None
        self.grpc_stub = None

        # Ensure DB metadata exists (in case migrations not run yet)
        try:
            UploadBase.metadata.create_all(engine)
        except Exception as e:
            logger.warning(f"DB metadata creation skipped: {e}")

        logger.info(f"Initializing Push Worker: {self.worker_id}")

    def connect_rabbitmq(self) -> bool:
        """Establish RabbitMQ connection with pub-sub pattern and optional queue fallback"""
        try:
            params = pika.URLParameters(Config.RABBITMQ_URL)
            self.connection = pika.BlockingConnection(params)
            self.channel = self.connection.channel()

            # Declare exchange (topic for routing)
            self.channel.exchange_declare(
                exchange=Config.RABBITMQ_EXCHANGE,
                exchange_type='topic',
                durable=True
            )

            # Declare exclusive, auto-deleted queue for this worker
            result = self.channel.queue_declare(queue='', exclusive=True)
            self.queue_name = result.method.queue

            # Bind queue to exchange with routing key
            self.channel.queue_bind(
                exchange=Config.RABBITMQ_EXCHANGE,
                queue=self.queue_name,
                routing_key=Config.RABBITMQ_ROUTING_KEY
            )

            logger.info(
                f"Connected to RabbitMQ exchange: {Config.RABBITMQ_EXCHANGE} | "
                f"queue: {self.queue_name} | routing: {Config.RABBITMQ_ROUTING_KEY}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            return False

    def connect_grpc(self) -> bool:
        """Establish gRPC connection (optional)"""
        if video_pb2_grpc is None:
            logger.warning("gRPC protobuf code not available; proceeding without gRPC")
            return False
        try:
            self.grpc_channel = grpc.insecure_channel(Config.GRPC_SERVER)
            self.grpc_stub = video_pb2_grpc.VideoServiceStub(self.grpc_channel)
            logger.info(f"Connected to gRPC server: {Config.GRPC_SERVER}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to gRPC: {e}")
            return False

    def update_video_status(self, video_id: str, status: VideoStatus, message: str = "") -> bool:
        """Update video status via gRPC if available, otherwise DB."""
        # Try gRPC first
        if self.grpc_stub and video_pb2:
            try:
                request = video_pb2.UpdateStatusRequest(
                    video_id=video_id,
                    status=status.value if isinstance(status, VideoStatus) else str(status),
                    worker_id=self.worker_id,
                    message=message
                )
                response = self.grpc_stub.UpdateVideoStatus(request)
                return bool(response.success)
            except Exception as e:
                logger.error(f"gRPC status update failed: {e}")

        # Fallback to direct DB update
        try:
            db = SessionLocal()
            video = db.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = status
                if status == VideoStatus.READY:
                    video.transcoded_at = datetime.utcnow()
                db.commit()
            db.close()
            return True
        except Exception as e:
            logger.error(f"Database status update failed: {e}")
            return False

    def report_progress(self, video_id: str, quality: str, progress: int, message: str = "") -> None:
        """Report transcoding progress via gRPC (best-effort)."""
        if not (self.grpc_stub and video_pb2):
            return
        try:
            request = video_pb2.TranscodeProgressRequest(
                video_id=video_id,
                worker_id=self.worker_id,
                progress_percent=int(progress),
                current_quality=quality,
                message=message or ""
            )
            self.grpc_stub.ReportTranscodeProgress(request)
        except Exception as e:
            logger.debug(f"Progress report failed: {e}")

    def process_job(self, job_data: dict) -> bool:
        """Process a single transcoding job."""
        video_id = job_data.get('video_id')
        filename = job_data.get('filename')
        filepath = job_data.get('filepath')

        logger.info(f"[{self.worker_id}] Processing job: {video_id} ({filename})")

        try:
            # Verify input file exists
            if not filepath or not os.path.exists(filepath):
                raise FileNotFoundError(f"Input file not found: {filepath}")

            # Update status to transcoding
            self.update_video_status(video_id, VideoStatus.TRANSCODING, f"Worker {self.worker_id} started")

            # Initialize transcoder
            transcoder = VideoTranscoder(Config)

            # Get video info
            video_info = transcoder.get_video_info(filepath)
            if video_info:
                logger.info(
                    f"Video info: duration={video_info.get('duration')}s, "
                    f"size={video_info.get('file_size')} bytes"
                )

            # Progress callback (log every 25%)
            def progress_callback(quality: str, progress_percent: int):
                self.report_progress(video_id, quality, progress_percent, "transcoding")
                if progress_percent % 25 == 0:
                    logger.info(f"[{self.worker_id}] {video_id} - {quality}: {progress_percent}%")

            # Transcode to all configured qualities
            start_time = time.time()
            results = transcoder.transcode_all_qualities(
                video_id=video_id,
                input_path=filepath,
                progress_callback=progress_callback
            )
            duration = time.time() - start_time

            success_count = len(results)
            total_qualities = len(Config.QUALITIES)
            logger.info(
                f"[{self.worker_id}] Transcoding finished in {duration:.2f}s: "
                f"{success_count}/{total_qualities} qualities ready"
            )

            if success_count > 0:
                # Mark as READY and store transcoded timestamp
                updated = self.update_video_status(
                    video_id,
                    VideoStatus.READY,
                    f"Transcoded to {success_count} qualities in {duration:.1f}s"
                )
                if not updated:
                    logger.warning("Status update (READY) failed")

                # Update transcoded_at in DB if not set via gRPC
                try:
                    db = SessionLocal()
                    video = db.query(Video).filter(Video.id == video_id).first()
                    if video and not video.transcoded_at:
                        video.transcoded_at = datetime.utcnow()
                        db.commit()
                    db.close()
                except Exception as e:
                    logger.error(f"Database update failed: {e}")

                return True

            # No successful outputs
            raise RuntimeError("No qualities produced")

        except Exception as e:
            logger.error(f"[{self.worker_id}] Job processing failed: {e}")
            self.update_video_status(video_id, VideoStatus.FAILED, str(e))
            return False

    def subscribe_and_process(self) -> None:
        """Subscribe to exchange and process incoming jobs."""
        logger.info(
            f"Worker {self.worker_id} subscribed to exchange: {Config.RABBITMQ_EXCHANGE} "
            f"(routing key: {Config.RABBITMQ_ROUTING_KEY})"
        )

        def callback(ch, method, properties, body):
            start_ts = time.time()
            try:
                job_data = json.loads(body.decode('utf-8'))
                logger.info(f"[{self.worker_id}] Received job: {job_data.get('video_id')}")

                success = self.process_job(job_data)
                if success:
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    logger.info(f"[{self.worker_id}] Job completed in {time.time() - start_ts:.2f}s")
                else:
                    # In pub-sub model, do not requeue failed messages
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                    logger.error(f"[{self.worker_id}] Job failed")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid job data: {e}")
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                logger.error(f"[{self.worker_id}] Unexpected error: {e}")
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

        # Start consuming
        self.channel.basic_consume(
            queue=self.queue_name,
            on_message_callback=callback,
            auto_ack=False
        )

        try:
            logger.info("Waiting for jobs... (Ctrl+C to exit)")
            self.channel.start_consuming()
        except KeyboardInterrupt:
            logger.info("Worker stopped by user")
            self.stop()

    def stop(self) -> None:
        """Graceful shutdown."""
        logger.info(f"[{self.worker_id}] Shutting down...")

        try:
            if self.channel and getattr(self.channel, 'is_open', False):
                try:
                    self.channel.stop_consuming()
                except Exception:
                    pass
                try:
                    self.channel.close()
                except Exception:
                    pass
        finally:
            if self.connection and getattr(self.connection, 'is_open', False):
                try:
                    self.connection.close()
                except Exception:
                    pass

        if self.grpc_channel:
            try:
                self.grpc_channel.close()
            except Exception:
                pass

        logger.info(f"[{self.worker_id}] Shutdown complete")

    def run(self) -> None:
        """Main worker routine."""
        if not self.connect_rabbitmq():
            logger.error("Failed to connect to RabbitMQ; exiting")
            return

        self.connect_grpc()  # optional

        # Ensure directories exist
        os.makedirs(Config.RAW_DIR, exist_ok=True)
        os.makedirs(Config.TRANSCODED_DIR, exist_ok=True)

        # Start subscriber
        try:
            self.subscribe_and_process()
        except Exception as e:
            logger.error(f"Worker error: {e}")
        finally:
            self.stop()


def main() -> None:
    logger.info("=" * 60)
    logger.info("Push-Based Transcoding Worker (Pub-Sub)")
    logger.info("=" * 60)
    logger.info(f"Worker ID: {os.getenv('WORKER_ID', 'auto')}" )
    logger.info(f"Exchange: {Config.RABBITMQ_EXCHANGE}")
    logger.info(f"Routing Key: {Config.RABBITMQ_ROUTING_KEY}")
    logger.info(f"Qualities: {Config.QUALITIES}")
    logger.info("=" * 60)

    worker = PushWorker()
    worker.run()


if __name__ == '__main__':
    main()


