import requests
import time
import sys

NGINX_LB = "http://localhost"
EDGE_1 = "http://localhost:9001"
EDGE_2 = "http://localhost:9002"
EDGE_3 = "http://localhost:9003"


def test_edge_health():
    '''Test all edge servers are healthy'''
    print("Testing edge server health...")
    
    edges = [
        ('Edge 1', EDGE_1),
        ('Edge 2', EDGE_2),
        ('Edge 3', EDGE_3),
        ('Nginx LB', NGINX_LB)
    ]
    
    for name, url in edges:
        try:
            response = requests.get(f"{url}/health", timeout=5)
            if response.status_code == 200:
                print(f"  {name}: healthy")
            else:
                print(f"  {name}: unhealthy ({response.status_code})")
        except Exception as e:
            print(f"  {name}: error - {e}")


def test_cache_behavior(video_id):
    '''Test CDN cache behavior'''
    print(f"\nTesting cache behavior for video {video_id}...")
    
    # First request (cache miss)
    print("\nFirst request (should be cache MISS)...")
    start = time.time()
    response = requests.get(
        f"{NGINX_LB}/api/v1/stream/{video_id}",
        params={'quality': '720p'},
        headers={'Range': 'bytes=0-1048575'}
    )
    first_time = time.time() - start
    
    print(f"  Status: {response.status_code}")
    print(f"  Time: {first_time:.3f}s")
    print(f"  X-Cache: {response.headers.get('X-Cache', 'N/A')}")
    print(f"  X-Edge-Server: {response.headers.get('X-Edge-Server', 'N/A')}")
    
    # Second request (cache hit)
    print("\nSecond request (should be cache HIT)...")
    time.sleep(1)
    
    start = time.time()
    response = requests.get(
        f"{NGINX_LB}/api/v1/stream/{video_id}",
        params={'quality': '720p'},
        headers={'Range': 'bytes=0-1048575'}
    )
    second_time = time.time() - start
    
    print(f"  Status: {response.status_code}")
    print(f"  Time: {second_time:.3f}s")
    print(f"  X-Cache: {response.headers.get('X-Cache', 'N/A')}")
    print(f"  X-Edge-Server: {response.headers.get('X-Edge-Server', 'N/A')}")
    
    # Compare times
    speedup = (first_time / second_time) if second_time > 0 else 0
    print(f"\nCache speedup: {speedup:.2f}x faster")
    
    if response.headers.get('X-Cache') == 'HIT':
        print("  Cache working correctly!")
    else:
        print("  Cache might not be working as expected")


def test_load_balancing():
    '''Test load balancing across edges'''
    print("\nTesting load balancing...")
    
    edge_servers = {}
    
    # Make multiple requests
    for i in range(10):
        try:
            response = requests.get(f"{NGINX_LB}/health", timeout=5)
            edge = response.headers.get('X-Edge-Server', 'unknown')
            edge_servers[edge] = edge_servers.get(edge, 0) + 1
        except Exception as e:
            print(f"  Request {i+1} failed: {e}")
    
    print("\\n  Request distribution:")
    for edge, count in edge_servers.items():
        print(f"    {edge}: {count} requests")
    
    # Check distribution is relatively even
    if len(edge_servers) >= 2:
        print("  ✅ Load balancing across multiple edges")
    else:
        print("  ⚠️  Only one edge server responding")


def test_cache_stats():
    '''Get cache statistics from edges'''
    print("\nCache statistics:")
    
    edges = [
        ('Edge 1', EDGE_1),
        ('Edge 2', EDGE_2),
        ('Edge 3', EDGE_3)
    ]
    
    for name, url in edges:
        try:
            response = requests.get(f"{url}/api/v1/cache/stats", timeout=5)
            if response.status_code == 200:
                stats = response.json()['data']
                print(f"\\n  {name} ({stats['location']}):")
                print(f"    Cached items: {stats['cached_items']}")
                print(f"    Cache size: {stats['cache_size_mb']:.2f} MB / {stats['max_size_mb']:.2f} MB")
                print(f"    Usage: {stats['usage_percent']:.1f}%")
        except Exception as e:
            print(f"  {name}: Error - {e}")


def main():
    print("=" * 60)
    print("CDN Edge Server Test Suite")
    print("=" * 60)
    
    # Test health
    test_edge_health()
    
    # Test load balancing
    test_load_balancing()
    
    # Get a video ID for testing
    print("\nTo test cache behavior, upload a video first:")
    print("   curl -X POST http://localhost:8001/api/v1/upload \\\\")
    print("    -F \"video=@test.mp4\" \\\\")
    print("    -F \"title=CDN Test\"")
    print("\\n   Then run: python test_cdn.py <video-id>")
    
    if len(sys.argv) > 1:
        video_id = sys.argv[1]
        test_cache_behavior(video_id)
    
    # Test cache stats
    test_cache_stats()
    
    print("\n" + "=" * 60)
    print("CDN tests complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()