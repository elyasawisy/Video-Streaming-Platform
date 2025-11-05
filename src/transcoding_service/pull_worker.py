"""
Pull-based Transcoding Worker
Polls RabbitMQ queue for transcoding jobs and processes them
"""
import os
import sys
import time
import json
import logging
import signal
from datetime import datetime
import pika
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from transcoding_service.config import Config
from transcoding_service.transcoder import VideoTranscoder
from upload_service.app import Video, VideoStatus, Base

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TranscodingWorker:
    """Pull-based worker that polls RabbitMQ for jobs"""
    
    def __init__(self, config):
        self.config = config
        self.transcoder = VideoTranscoder(config)
        self.running = True
        self.current_job = None
        
        # Database setup
        self.engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(bind=self.engine)
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
    
    def get_rabbitmq_connection(self):
        """Get RabbitMQ connection"""
        try:
            params = pika.URLParameters(self.config.RABBITMQ_URL)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue=self.config.RABBITMQ_QUEUE, durable=True)
            # Set QoS to process one message at a time
            channel.basic_qos(prefetch_count=1)
            return connection, channel
        except Exception as e:
            logger.error(f"RabbitMQ connection failed: {e}")
            return None, None
    
    def update_video_status(self, video_id, status, duration=None):
        """Update video status in database"""
        try:
            db = self.SessionLocal()
            video = db.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = status
                if duration is not None:
                    video.duration = duration
                if status == VideoStatus.READY:
                    video.transcoded_at = datetime.utcnow()
                db.commit()
            db.close()
        except Exception as e:
            logger.error(f"Error updating video status: {e}")
    
    def process_job(self, job_data):
        """Process a transcoding job"""
        video_id = job_data.get('video_id')
        filepath = job_data.get('filepath')
        
        if not video_id or not filepath:
            logger.error("Invalid job data: missing video_id or filepath")
            return False
        
        if not os.path.exists(filepath):
            logger.error(f"Input file not found: {filepath}")
            self.update_video_status(video_id, VideoStatus.FAILED)
            return False
        
        try:
            # Update status to transcoding
            self.update_video_status(video_id, VideoStatus.TRANSCODING)
            
            # Get video info
            video_info = self.transcoder.get_video_info(filepath)
            if video_info:
                self.update_video_status(video_id, VideoStatus.TRANSCODING, video_info['duration'])
            
            # Progress callback
            def progress_callback(quality, progress):
                if progress % 10 == 0:  # Log every 10%
                    logger.info(f"Video {video_id}: {quality} - {progress}%")
            
            # Transcode to all qualities
            logger.info(f"Starting transcoding for video {video_id}")
            results = self.transcoder.transcode_all_qualities(
                video_id,
                filepath,
                progress_callback=progress_callback
            )
            
            # Check if all qualities were transcoded successfully
            if len(results) == len(self.config.QUALITIES):
                self.update_video_status(video_id, VideoStatus.READY)
                logger.info(f"Transcoding complete for video {video_id}")
                return True
            else:
                logger.warning(f"Partial transcoding for video {video_id}: {len(results)}/{len(self.config.QUALITIES)}")
                # Still mark as ready if at least one quality succeeded
                if results:
                    self.update_video_status(video_id, VideoStatus.READY)
                    return True
                else:
                    self.update_video_status(video_id, VideoStatus.FAILED)
                    return False
                    
        except Exception as e:
            logger.error(f"Error processing job for video {video_id}: {e}")
            self.update_video_status(video_id, VideoStatus.FAILED)
            return False
    
    def run(self):
        """Main worker loop"""
        logger.info(f"Starting transcoding worker {self.config.WORKER_ID}")
        
        while self.running:
            connection = None
            channel = None
            
            try:
                connection, channel = self.get_rabbitmq_connection()
                if not channel:
                    logger.warning("Failed to connect to RabbitMQ, retrying...")
                    time.sleep(self.config.POLL_INTERVAL)
                    continue
                
                logger.info("Connected to RabbitMQ, waiting for jobs...")
                
                # Consume messages
                def callback(ch, method, properties, body):
                    try:
                        job_data = json.loads(body.decode('utf-8'))
                        self.current_job = job_data
                        
                        logger.info(f"Received job: {job_data.get('video_id')}")
                        
                        # Process job
                        success = self.process_job(job_data)
                        
                        if success:
                            ch.basic_ack(delivery_tag=method.delivery_tag)
                            logger.info(f"Job completed successfully: {job_data.get('video_id')}")
                        else:
                            # Reject and requeue
                            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                            logger.warning(f"Job failed, requeuing: {job_data.get('video_id')}")
                        
                        self.current_job = None
                        
                    except Exception as e:
                        logger.error(f"Error in callback: {e}")
                        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                        self.current_job = None
                
                channel.basic_consume(
                    queue=self.config.RABBITMQ_QUEUE,
                    on_message_callback=callback
                )
                
                # Start consuming (blocking)
                channel.start_consuming()
                
            except KeyboardInterrupt:
                logger.info("Received interrupt signal")
                self.running = False
            except pika.exceptions.ConnectionClosed:
                logger.warning("RabbitMQ connection closed, reconnecting...")
                if channel:
                    channel.stop_consuming()
                time.sleep(self.config.POLL_INTERVAL)
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                if channel:
                    try:
                        channel.stop_consuming()
                    except:
                        pass
                time.sleep(self.config.POLL_INTERVAL)
            finally:
                if connection and not connection.is_closed:
                    connection.close()
        
        logger.info("Worker shutting down...")


def main():
    """Main entry point"""
    config = Config()
    worker = TranscodingWorker(config)
    worker.run()


if __name__ == '__main__':
    main()

