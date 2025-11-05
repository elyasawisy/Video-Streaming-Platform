"""
gRPC Client for Video Service
Example usage of the gRPC service
"""

import grpc
from . import video_pb2
from . import video_pb2_grpc
import os

class VideoServiceClient:
    """Client for interacting with Video Service via gRPC"""
    
    def __init__(self, host='localhost', port=50051):
        self.channel = grpc.insecure_channel(f'{host}:{port}')
        self.stub = video_pb2_grpc.VideoServiceStub(self.channel)
    
    def get_video(self, video_id):
        """Get video information"""
        try:
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
        except grpc.RpcError as e:
            print(f"gRPC Error: {e.code()} - {e.details()}")
            return None
    
    def update_video_status(self, video_id, status, worker_id='client', message=''):
        """Update video processing status"""
        try:
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
        except grpc.RpcError as e:
            print(f"gRPC Error: {e.code()} - {e.details()}")
            return None
    
    def stream_video_chunks(self, video_id, quality='720p', offset=0, chunk_size=65536):
        """Stream video chunks (for testing)"""
        try:
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
                
                print(f"Received chunk {chunk_count}: {chunk.size} bytes at offset {chunk.offset}")
                
                if chunk.is_last:
                    print(f"Stream complete: {chunk_count} chunks, {total_bytes} total bytes")
                    break
            
            return {'chunks': chunk_count, 'total_bytes': total_bytes}
            
        except grpc.RpcError as e:
            print(f"gRPC Error: {e.code()} - {e.details()}")
            return None
    
    def report_progress(self, video_id, worker_id, progress_percent, quality, message=''):
        """Report transcoding progress"""
        try:
            request = video_pb2.TranscodeProgressRequest(
                video_id=video_id,
                worker_id=worker_id,
                progress_percent=progress_percent,
                current_quality=quality,
                message=message
            )
            response = self.stub.ReportTranscodeProgress(request)
            
            return response.success
        except grpc.RpcError as e:
            print(f"gRPC Error: {e.code()} - {e.details()}")
            return False
    
    def get_queue_status(self, queue_name='transcode_queue'):
        """Get transcoding queue status"""
        try:
            request = video_pb2.QueueStatusRequest(queue_name=queue_name)
            response = self.stub.GetQueueStatus(request)
            
            return {
                'pending_jobs': response.pending_jobs,
                'active_workers': response.active_workers,
                'video_ids': list(response.video_ids)
            }
        except grpc.RpcError as e:
            print(f"gRPC Error: {e.code()} - {e.details()}")
            return None
    
    def close(self):
        """Close the gRPC channel"""
        self.channel.close()


# Example usage and tests
def test_grpc_client():
    """Test gRPC client functionality"""
    print("=" * 60)
    print("gRPC Client Test Suite")
    print("=" * 60)
    
    client = VideoServiceClient()
    
    # Test 1: Get queue status
    print("\nTesting GetQueueStatus...")
    status = client.get_queue_status()
    if status:
        print(f"Queue Status:")
        print(f"   Pending jobs: {status['pending_jobs']}")
        print(f"   Active workers: {status['active_workers']}")
        print(f"   Video IDs: {status['video_ids'][:3]}...")
    
    # Test 2: Get video info (you'll need a real video_id)
    print("\nTesting GetVideo...")
    print("   (Skipping - need actual video_id from upload)")
    
    # Example with actual video_id:
    # video_info = client.get_video('some-video-id')
    # if video_info:
    #     print(f"Video Info: {video_info['title']}")
    
    # Test 3: Report progress
    print("\nTesting ReportTranscodeProgress...")
    success = client.report_progress(
        video_id='test-video-id',
        worker_id='worker-1',
        progress_percent=50,
        quality='720p',
        message='Transcoding in progress'
    )
    print(f"Progress reported: {success}")
    
    client.close()
    print("\n" + "=" * 60)
    print("gRPC tests completed")
    print("=" * 60)


if __name__ == '__main__':
    test_grpc_client()