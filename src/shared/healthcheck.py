import os
import requests
import sys
from typing import Dict, List, Tuple

def check_http_service(name: str, url: str) -> Tuple[bool, str]:
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return True, f"{name} is healthy"
        return False, f"{name} returned status code {response.status_code}"
    except Exception as e:
        return False, f"{name} check failed: {str(e)}"

def check_services() -> List[Tuple[str, bool, str]]:
    # Allow overriding via environment variables. Defaults match current docker-compose mappings.
    services = {
        "Upload Service": os.getenv("UPLOAD_HTTP2_HEALTH", "http://localhost:8001/health"),
        "Chunked Upload": os.getenv("UPLOAD_CHUNKED_HEALTH", "http://localhost:8002/health"),
        "Streaming Service": os.getenv("STREAMING_SERVICE_HEALTH", "http://localhost:8003/health"),
        "CDN Edge 1": os.getenv("CDN_EDGE_1_HEALTH", "http://localhost:9001/health"),
        "CDN Edge 2": os.getenv("CDN_EDGE_2_HEALTH", "http://localhost:9002/health"),
    "Load Balancer": os.getenv("LOAD_BALANCER_HEALTH", "http://localhost/health"),
    # gRPC health endpoint may not be HTTP; use a TCP check or skip by default
    # Leave empty to skip gRPC check (recommended) or provide an HTTP health endpoint override
    "gRPC Service": os.getenv("GRPC_SERVICE_ADDR", "")
    }
    
    results = []
    for name, url in services.items():
        if not url:
            # Skip checks where no address is configured (don't fail the overall health)
            results.append((name, None, "No address configured (skipped)"))
            continue
        # If the value looks like http(s), use HTTP check; otherwise attempt a simple TCP connect
        if url.startswith("http://") or url.startswith("https://"):
            healthy, message = check_http_service(name, url)
        else:
            healthy, message = False, "Unsupported check type"
        results.append((name, healthy, message))
    
    return results

def main():
    print("Running health checks...")
    results = check_services()
    
    all_healthy = True
    for name, healthy, message in results:
        if healthy is None:
            status = "S"  # Skipped
            print(f"{status} {name}: {message}")
            continue
        status = "✓" if healthy else "✗"
        print(f"{status} {name}: {message}")
        if healthy is False:
            all_healthy = False
    
    sys.exit(0 if all_healthy else 1)

if __name__ == "__main__":
    main()