"""
gRPC Client for Video Service with resilience patterns
"""
import os
import sys
import grpc
import logging

# Add gRPC directory to path for direct execution
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

import video_pb2
import video_pb2_grpc
from resiliency import (
    GrpcClientWrapper, CircuitConfig, RetryConfig, grpc
)

logger = logging.getLogger(__name__)

class VideoServiceClient:
    """Client for interacting with Video Service via gRPC with resilience patterns"""
    
    def __init__(self, host='localhost', port=50051):
        self.channel = grpc.insecure_channel(f'{host}:{port}')
        self.stub = video_pb2_grpc.VideoServiceStub(self.channel)
        
        # Configure resilience patterns
        self.circuit_config = CircuitConfig(
            failure_threshold=5,
            success_threshold=2,
            timeout=30,
            window_size=60,
            excluded_errors=[grpc.StatusCode.NOT_FOUND]
        )
        
        self.retry_config = RetryConfig(
            max_attempts=3,
            initial_backoff=1.0,
            max_backoff=10.0,
            backoff_multiplier=2.0,
            retryable_status_codes=[
                grpc.StatusCode.UNAVAILABLE,
                grpc.StatusCode.DEADLINE_EXCEEDED,
                grpc.StatusCode.RESOURCE_EXHAUSTED
            ]
        )
        
        self.client_wrapper = GrpcClientWrapper(
            service_name="video_service",
            circuit_config=self.circuit_config,
            retry_config=self.retry_config
        )
    
    def get_video(self, video_id):
        """Get video information with resilience"""
        def _get_video():
            request = video_pb2.VideoRequest(
                video_id=video_id,
                include_metadata=True
            )
            response = self.stub.GetVideo(request)
            
            return {
                'video_id': response.video_id,
                'title': response.title,
                'filename': response.filename,
                'file_size': response.file_size,
                'status': response.status,
                'mime_type': response.mime_type,
                'created_at': response.created_at,
                'metadata': dict(response.metadata)
            }
        
        try:
            return self.client_wrapper.call(_get_video)
        except grpc.RpcError as e:
            logger.error(f"Failed to get video {video_id}: {e.code()} - {e.details()}")
            return None
    
    def update_video_status(self, video_id, status, worker_id='client', message=''):
        """Update video processing status with resilience"""
        def _update_status():
            request = video_pb2.UpdateStatusRequest(
                video_id=video_id,
                status=status,
                worker_id=worker_id,
                message=message
            )
            response = self.stub.UpdateVideoStatus(request)
            
            return {
                'success': response.success,
                'message': response.message,
                'timestamp': response.timestamp
            }
        
        try:
            return self.client_wrapper.call(_update_status)
        except grpc.RpcError as e:
            logger.error(f"Failed to update status for video {video_id}: {e.code()} - {e.details()}")
            return None
    
    def stream_video_chunks(self, video_id, quality='720p', offset=0, chunk_size=65536):
        """Stream video chunks with resilience"""
        def _stream_chunks():
            request = video_pb2.ChunkRequest(
                video_id=video_id,
                offset=offset,
                chunk_size=chunk_size,
                quality=quality
            )
            
            total_bytes = 0
            chunk_count = 0
            
            for chunk in self.stub.GetVideoChunks(request):
                chunk_count += 1
                total_bytes += chunk.size
                
                logger.debug(f"Received chunk {chunk_count}: {chunk.size} bytes at offset {chunk.offset}")
                
                if chunk.is_last:
                    logger.info(f"Stream complete: {chunk_count} chunks, {total_bytes} total bytes")
                    break
            
            return {'chunks': chunk_count, 'total_bytes': total_bytes}
        
        try:
            return self.client_wrapper.call(_stream_chunks)
        except grpc.RpcError as e:
            logger.error(f"Failed to stream video {video_id}: {e.code()} - {e.details()}")
            return None
    
    def report_progress(self, video_id, worker_id, progress_percent, quality, message=''):
        """Report transcoding progress with resilience"""
        def _report_progress():
            request = video_pb2.TranscodeProgressRequest(
                video_id=video_id,
                worker_id=worker_id,
                progress_percent=progress_percent,
                current_quality=quality,
                message=message
            )
            response = self.stub.ReportTranscodeProgress(request)
            return response.success
        
        try:
            return self.client_wrapper.call(_report_progress)
        except grpc.RpcError as e:
            logger.error(f"Failed to report progress for video {video_id}: {e.code()} - {e.details()}")
            return False
    
    def get_queue_status(self, queue_name='transcode_queue'):
        """Get transcoding queue status with resilience"""
        def _get_status():
            request = video_pb2.QueueStatusRequest(queue_name=queue_name)
            response = self.stub.GetQueueStatus(request)
            
            return {
                'pending_jobs': response.pending_jobs,
                'active_workers': response.active_workers,
                'video_ids': list(response.video_ids)
            }
        
        try:
            return self.client_wrapper.call(_get_status)
        except grpc.RpcError as e:
            logger.error(f"Failed to get queue status: {e.code()} - {e.details()}")
            return None
    
    def get_client_metrics(self):
        """Get circuit breaker metrics"""
        return self.client_wrapper.circuit.get_metrics()
    
    def close(self):
        """Close the gRPC channel"""
        self.channel.close()


def test_grpc_client(host='localhost', port=50051):
    """Test gRPC client functionality with resilience patterns"""
    logger.info("=" * 60)
    logger.info("gRPC Client Test Suite")
    logger.info("=" * 60)
    
    client = VideoServiceClient(host, port)
    
    # Test 1: Get queue status
    logger.info("\nTesting GetQueueStatus...")
    status = client.get_queue_status()
    if status:
        logger.info("Queue Status:")
        logger.info(f"   Pending jobs: {status['pending_jobs']}")
        logger.info(f"   Active workers: {status['active_workers']}")
        logger.info(f"   Video IDs: {status['video_ids'][:3]}...")
    
    # Test 2: Get client metrics
    logger.info("\nTesting Client Metrics...")
    metrics = client.get_client_metrics()
    logger.info(f"Circuit State: {metrics.current_state}")
    logger.info(f"Total Requests: {metrics.total_requests}")
    logger.info(f"Successful Requests: {metrics.successful_requests}")
    logger.info(f"Failed Requests: {metrics.failed_requests}")
    logger.info(f"Rejected Requests: {metrics.rejected_requests}")
    logger.info(f"Average Response Time: {metrics.avg_response_time:.2f}s")
    
    # Test 3: Report progress
    logger.info("\nTesting ReportTranscodeProgress...")
    success = client.report_progress(
        video_id='test-video-id',
        worker_id='worker-1',
        progress_percent=50,
        quality='720p',
        message='Transcoding in progress'
    )
    logger.info(f"Progress reported: {success}")
    
    client.close()
    logger.info("\n" + "=" * 60)
    logger.info("gRPC tests completed")
    logger.info("=" * 60)


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    test_grpc_client()