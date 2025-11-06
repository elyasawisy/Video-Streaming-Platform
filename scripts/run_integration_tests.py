"""
Integration test runner for Video Streaming Platform

What it does:
- Builds and starts services via docker-compose
- Waits for core services to become reachable:
  - Postgres TCP (5432)
  - Redis TCP (6379)
  - RabbitMQ management HTTP (http://localhost:15672/)
  - Upload HTTP/2 service health (http://localhost:8001/health)
  - Chunked upload service health (http://localhost:8002/health)
  - Streaming service health (http://localhost:8003/health)
- Runs pytest for the upload tests
- Prints a summary and optionally tears down services

Usage:
  python scripts\\run_integration_tests.py [--no-build] [--no-teardown]

Note: This script expects Docker and docker-compose to be available on PATH.

"""
import argparse
import os
import subprocess
import sys
import time
import socket
import urllib.request
import urllib.error

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
os.chdir(ROOT)

DEFAULT_WAIT_TIMEOUT = 180  # seconds
POLL_INTERVAL = 3

SERVICES_TO_CHECK = [
    ("Postgres TCP", "localhost", 5432),
    ("Redis TCP", "localhost", 6379),
    ("RabbitMQ HTTP", "http://localhost:15672/"),
    ("Upload HTTP/2", "http://localhost:8001/health"),
    ("Chunked Upload", "http://localhost:8002/health"),
    ("Streaming Service", "http://localhost:8003/health"),
]


def run_cmd(cmd, check=True, capture=False):
    print(f"\n> Running: {' '.join(cmd)}")
    try:
        if capture:
            return subprocess.run(cmd, check=check, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        else:
            return subprocess.run(cmd, check=check)
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}")
        if capture and hasattr(e, 'output'):
            print(e.output)
        if check:
            raise
        return e


def wait_for_tcp(host, port, timeout=DEFAULT_WAIT_TIMEOUT):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=5):
                print(f"[OK] TCP {host}:{port} reachable")
                return True
        except OSError:
            print(f"Waiting for TCP {host}:{port}...")
            time.sleep(POLL_INTERVAL)
    print(f"[FAIL] TCP {host}:{port} not reachable after {timeout}s")
    return False


def wait_for_http(url, timeout=DEFAULT_WAIT_TIMEOUT):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                code = resp.getcode()
                if 200 <= code < 400:
                    print(f"[OK] HTTP {url} returned {code}")
                    return True
                else:
                    print(f"HTTP {url} returned {code}, waiting...")
        except urllib.error.URLError as e:
            print(f"Waiting for HTTP {url}... ({e.reason})")
        except Exception as ex:
            print(f"Waiting for HTTP {url}... ({ex})")
        time.sleep(POLL_INTERVAL)
    print(f"[FAIL] HTTP {url} not healthy after {timeout}s")
    return False


def check_services(timeout=DEFAULT_WAIT_TIMEOUT):
    print("\nChecking service readiness...")
    all_ok = True
    for item in SERVICES_TO_CHECK:
        if len(item) == 3 and isinstance(item[2], int):
            # TCP check
            _, host, port = item
            ok = wait_for_tcp(host, port, timeout=timeout)
        else:
            # HTTP check
            _, url = item
            ok = wait_for_http(url, timeout=timeout)
        all_ok = all_ok and ok
    return all_ok


def init_database():
    """Initialize database using the init script"""
    init_script = os.path.join(ROOT, 'scripts', 'init_database.py')
    result = run_cmd([sys.executable, init_script], check=False, capture=True)
    return result.returncode == 0 if isinstance(result, subprocess.CompletedProcess) else False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-build', action='store_true', help='Do not rebuild images')
    parser.add_argument('--no-teardown', action='store_true', help="Don't tear down services after tests")
    parser.add_argument('--skip-db-init', action='store_true', help="Skip database initialization")
    parser.add_argument('--timeout', type=int, default=DEFAULT_WAIT_TIMEOUT, help='Max wait time for services')
    args = parser.parse_args()

    build_flag = [] if args.no_build else ['--build']

    try:
        print('\n== Integration test runner starting ==')
        print('Working dir:', ROOT)

        # 1) Start core services first (postgres, redis, rabbitmq)
        core_services = ['postgres', 'redis', 'rabbitmq']
        cmd_up_core = ['docker-compose', 'up', '-d'] + build_flag + core_services
        run_cmd(cmd_up_core, check=True)

        # 2) Initialize database if needed
        if not args.skip_db_init:
            print("\nInitializing database...")
            if not init_database():
                print("Database initialization failed!")
                raise SystemExit(1)

        # 3) Start remaining services
        cmd_up = ['docker-compose', 'up', '-d'] + build_flag
        run_cmd(cmd_up, check=True)

        # 2) Wait for readiness
        ok = check_services(timeout=args.timeout)
        if not ok:
            print('\nOne or more services failed to become ready. Gathering docker-compose ps and logs (tail)...')
            run_cmd(['docker-compose', 'ps'], check=False)
            # print last 200 lines of logs for each service
            run_cmd(['docker-compose', 'logs', '--tail', '200'], check=False)
            raise SystemExit(2)

        # 3) Run tests (pytest for upload services)
        print('\n== Running tests ==')
        test_files = [
            'src/upload_service/test_upload_http2.py',
            'src/chunked_upload_service/test_upload_chunked.py'
        ]

        # Run pytest via python -m pytest so that venv/site-packages resolution uses python used to run the script
        pytest_cmd = [sys.executable, '-m', 'pytest', '-q'] + test_files
        result = run_cmd(pytest_cmd, check=False, capture=True)

        if isinstance(result, subprocess.CompletedProcess):
            print('\n== Pytest output ==')
            print(result.stdout)
            returncode = result.returncode
        else:
            returncode = getattr(result, 'returncode', 1)

        if returncode == 0:
            print('\n== ALL TESTS PASSED ==')
        else:
            print(f"\n== SOME TESTS FAILED (exit code {returncode}) ==")
            # dump docker-compose logs for debugging
            run_cmd(['docker-compose', 'logs', '--tail', '500'], check=False)

        return returncode

    except KeyboardInterrupt:
        print('Interrupted by user')
        return 130
    except Exception as e:
        print('Error during test run:', str(e))
        return 1
    finally:
        if args.no_teardown:
            print('\nLeaving services running (no-teardown).')
        else:
            print('\nTearing down services...')
            try:
                run_cmd(['docker-compose', 'down'], check=False)
            except Exception as e:
                print('Failed to tear down services:', e)


if __name__ == '__main__':
    code = main()
    sys.exit(code)
