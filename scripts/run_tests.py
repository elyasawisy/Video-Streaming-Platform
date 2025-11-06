import os
import sys
import unittest
import docker
import time
from typing import List
import subprocess

def run_docker_compose():
    print("Starting services with docker-compose...")
    subprocess.run(["docker-compose", "up", "-d"], check=True)
    time.sleep(10)  # Wait for services to be ready

def run_health_checks():
    print("Running health checks...")
    health_check_script = os.path.join("src", "shared", "healthcheck.py")
    result = subprocess.run([sys.executable, health_check_script], capture_output=True, text=True)
    if result.returncode != 0:
        print("Health checks failed:")
        print(result.stdout)
        print(result.stderr)
        sys.exit(1)
    print("Health checks passed")

def discover_and_run_tests(pattern: str = "test_*.py") -> bool:
    """Discover and run tests matching the pattern."""
    loader = unittest.TestLoader()
    tests = loader.discover(".", pattern=pattern)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(tests)
    return result.wasSuccessful()

def main():
    try:
        run_docker_compose()
        run_health_checks()
        
        print("\nRunning integration tests...")
        success = discover_and_run_tests()
        
        if not success:
            print("Some tests failed!")
            sys.exit(1)
        
        print("\nAll tests passed successfully!")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)
    finally:
        print("\nCleaning up...")
        subprocess.run(["docker-compose", "down"], check=True)

if __name__ == "__main__":
    main()