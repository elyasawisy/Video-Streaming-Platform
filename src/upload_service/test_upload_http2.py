import requests
import time
import os
import sys

API_URL = "http://localhost:8001"

def test_health_check():
    """Test health endpoint"""
    print("Testing health check...")
    try:
        response = requests.get(f"{API_URL}/health")
        if response.status_code == 200:
            print("Health check passed")
            print(f"   Response: {response.json()}")
            return True
        else:
            print(f"Health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"Connection failed: {e}")
        return False

def create_test_video(size_mb=10):
    """Create a test video file"""
    filename = f"test_video_{size_mb}mb.mp4"
    if not os.path.exists(filename):
        print(f"Creating {size_mb}MB test video...")
        # Create a dummy file for testing
        with open(filename, 'wb') as f:
            f.write(os.urandom(size_mb * 1024 * 1024))
        print(f"Test video created: {filename}")
    return filename

def test_upload(filename, title="Test Video Upload"):
    """Test video upload"""
    print(f"\nUploading {filename}...")
    
    start_time = time.time()
    
    try:
        with open(filename, 'rb') as video_file:
            files = {'video': (filename, video_file, 'video/mp4')}
            data = {
                'title': title,
                'uploader_id': 'test-user-123'
            }
            
            response = requests.post(
                f"{API_URL}/api/v1/upload",
                files=files,
                data=data,
                timeout=300  # 5 minutes timeout
            )
            
            upload_time = time.time() - start_time
            
            if response.status_code == 201:
                result = response.json()
                print(f"Upload successful!")
                print(f"   Video ID: {result['data']['id']}")
                print(f"   Upload Time: {upload_time:.2f}s")
                print(f"   Status: {result['data']['status']}")
                print(f"   Throughput: {result['data'].get('throughput_bps', 0) / 1024 / 1024:.2f} MB/s")
                return result['data']['id']
            else:
                print(f"Upload failed: {response.status_code}")
                print(f"   Response: {response.text}")
                return None
                
    except Exception as e:
        print(f"Upload error: {e}")
        return None

def test_get_video_status(video_id):
    """Test getting video status"""
    print(f"\nChecking video status...")
    try:
        response = requests.get(f"{API_URL}/api/v1/videos/{video_id}")
        if response.status_code == 200:
            result = response.json()
            print(f"Status retrieved")
            print(f"   Status: {result['data']['status']}")
            print(f"   File Size: {result['data']['file_size'] / 1024 / 1024:.2f} MB")
            return True
        else:
            print(f"Status check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_list_videos():
    """Test listing videos"""
    print(f"\nListing videos...")
    try:
        response = requests.get(f"{API_URL}/api/v1/videos")
        if response.status_code == 200:
            result = response.json()
            print(f"Retrieved {result['count']} videos")
            for video in result['data'][:3]:  # Show first 3
                print(f"   - {video['title']} ({video['status']})")
            return True
        else:
            print(f"List failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_get_metrics():
    """Test getting upload metrics"""
    print(f"\nGetting upload metrics...")
    try:
        response = requests.get(f"{API_URL}/api/v1/metrics")
        if response.status_code == 200:
            result = response.json()
            print(f"Retrieved metrics for {result['count']} uploads")
            if result['averages']:
                print(f"   Avg Upload Time: {result['averages']['upload_duration_ms'] / 1000:.2f}s")
                print(f"   Avg Throughput: {result['averages']['throughput_bps'] / 1024 / 1024:.2f} MB/s")
            return True
        else:
            print(f"Metrics failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"Error: {e}")
        return False

def main():
    print("=" * 60)
    print("HTTP/2 Upload Service Test Suite")
    print("=" * 60)
    
    # Test 1: Health Check
    if not test_health_check():
        print("\nService is not running. Start it with:")
        print("   docker-compose up upload_service_http2")
        sys.exit(1)
    
    # Test 2: Create and upload small video
    test_file = create_test_video(10)  # 10MB test file
    video_id = test_upload(test_file, "HTTP/2 Test Upload - 10MB")
    
    if video_id:
        # Test 3: Check video status
        time.sleep(2)  # Wait a bit
        test_get_video_status(video_id)
        
        # Test 4: List videos
        test_list_videos()
        
        # Test 5: Get metrics
        test_get_metrics()
        
        print("\n" + "=" * 60)
        print("All tests completed!")
        print("=" * 60)
    else:
        print("\nUpload test failed, skipping remaining tests")
    
    # Cleanup
    if os.path.exists(test_file):
        os.remove(test_file)
        print(f"\nCleaned up test file: {test_file}")

if __name__ == "__main__":
    main()