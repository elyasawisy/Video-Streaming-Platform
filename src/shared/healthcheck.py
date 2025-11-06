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
    services = {
        "Upload Service": "http://localhost:3000/health",
        "Chunked Upload": "http://localhost:3001/health",
        "Streaming Service": "http://localhost:5000/health",
        "CDN Edge 1": "http://localhost:8081/health",
        "CDN Edge 2": "http://localhost:8082/health",
        "Load Balancer": "http://localhost:8080/health",
        "gRPC Service": "http://localhost:50051"  # Note: gRPC needs different check
    }
    
    results = []
    for name, url in services.items():
        healthy, message = check_http_service(name, url)
        results.append((name, healthy, message))
    
    return results

def main():
    print("Running health checks...")
    results = check_services()
    
    all_healthy = True
    for name, healthy, message in results:
        status = "✓" if healthy else "✗"
        print(f"{status} {name}: {message}")
        if not healthy:
            all_healthy = False
    
    sys.exit(0 if all_healthy else 1)

if __name__ == "__main__":
    main()