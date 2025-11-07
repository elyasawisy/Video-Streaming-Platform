# Video Streaming Platform

A scalable video streaming platform implementing modern upload, transcoding, and delivery approaches.

## Scenario & Rationale

We chose the Video Streaming Platform scenario to tackle complex real-world challenges in modern video delivery:

- Large file handling (100MB-2GB uploads)
- Asynchronous processing (transcoding queue)
- High concurrency (50,000+ viewers)
- Distributed content delivery
- Resilient upload mechanisms
- Efficient caching strategies

## Tech Stack

### Core Technologies
- Python 3.11 (FastAPI/Flask services)
- PostgreSQL (metadata storage)
- Redis (caching, progress tracking)
- RabbitMQ (job queues)
- NGINX (load balancer, reverse proxy)
- HAProxy (load balancer alternative)
- Docker & Docker Compose (containerization)

### Implementation Approaches

#### Upload Protocols
1. HTTP/2 Streaming Upload
   - Direct streaming with backpressure
   - Native multiplexing
   - Single connection efficiency
   
2. Chunked Upload with Resume
   - Fault-tolerant uploads
   - Progress tracking
   - Parallel chunk processing

#### Worker Patterns
1. Pull-based Workers
   - Workers poll for jobs
   - Self-regulating workload
   - Simple implementation
   
2. Push-based Workers
   - Pub/sub pattern
   - Real-time job distribution
   - Lower latency

#### Content Delivery
1. Edge Caching (CDN Simulation)
   - Multiple edge servers
   - Geographical distribution
   - Cache synchronization
   
2. Reverse Proxy Cache
   - Local cache layer
   - Cache invalidation
   - Bandwidth optimization

## Quick Start

### Prerequisites
- Docker and Docker Compose
- 16GB+ RAM recommended
- 50GB+ free disk space

### Basic Setup
```bash
# Clone the repository
git clone https://github.com/elyasawisy/Video-Streaming-Platform.git
cd Video-Streaming-Platform

# Start all services
docker-compose up -d
```

### Running Load Tests
```bash
# Install k6 testing tool
# For Windows:
winget install k6 

# For macOS:
brew install k6

# For Linux:
snap install k6

# Run the load tests
cd load_tests
k6 run scenarios/upload_test.js  # Test uploads
k6 run scenarios/streaming_test.js  # Test video streaming
k6 run scenarios/concurrent_test.js  # Test concurrent viewers
```

## Architecture Overview

### Key Components

1. **Upload Services**
   - HTTP/2 Upload Service (8001)
   - Chunked Upload Service (8002)
   - Progress tracking
   - Resumable transfers

2. **Transcoding Pipeline**
   - Queue management
   - Worker pools
   - Format conversion
   - Quality variants

3. **Content Delivery**
   - Edge server network
   - Caching layers
   - Load balancing
   - Viewer session management

4. **Supporting Infrastructure**
   - PostgreSQL (metadata)
   - Redis (caching)
   - RabbitMQ (queues)
   - Monitoring

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed design documentation.

## Project Structure

```
.
├── docker-compose.yml      # Container orchestration
├── load_tests/            # k6 load testing scripts
├── src/
│   ├── upload_service/    # HTTP/2 upload implementation
│   ├── chunked_upload/    # Chunked upload implementation
│   ├── transcoding/       # Video processing workers
│   ├── streaming/         # Video delivery service
│   ├── cdn_edge/         # Edge server implementation
│   └── shared/           # Common utilities
└── docs/
    ├── ARCHITECTURE.md   # Detailed system design
    └── ANALYSIS.pdf      # Performance analysis report
```

## Configuration

All services use environment variables for configuration. See `.env.example` for available options.

Key configuration files:
- `docker-compose.yml` - Container settings
- `src/*/config.py` - Service configurations
- `load_balancer/nginx.conf` - NGINX config
- `load_balancer/haproxy.cfg` - HAProxy config

## Performance Analysis

See [ANALYSIS_REPORT.pdf](docs/ANALYSIS_REPORT.pdf) for detailed performance comparison between approaches.

Key findings:
- Chunked uploads provide 99.9% reliability vs 92% for HTTP/2 streaming under network issues
- Push-based workers reduce job latency by 65% vs pull-based
- Edge caching improves TTFB by 82% for distant viewers
- Cache hit rates reach 94% for popular content

## Comprehensive Testing Guide

### 1. Start Required Infrastructure

First, start all required infrastructure services:

```bash
# Start infrastructure services
docker-compose up -d postgres redis rabbitmq

# Wait for services to be ready (about 30 seconds)
docker-compose ps
```

### 2. Start Core Services

Start all core services in the correct order:

```bash
# Start upload services
docker-compose up -d upload_service_http2 upload_service_chunked

# Start transcoding workers
docker-compose up -d worker_pull worker_push

# Start streaming service
docker-compose up -d streaming_service

# Start CDN edge servers
docker-compose up -d cdn_edge1 cdn_edge2

# Start load balancers
docker-compose up -d nginx haproxy

# Verify all services are running
docker-compose ps
```

### 3. Run Individual Component Tests

Test each component separately:

```bash
# HTTP/2 Upload Tests
python src/upload_service/test_upload_http2.py

# Chunked Upload Tests
python src/chunked_upload_service/test_upload_chunked.py

# CDN Tests
python src/cdn_edge/test_cdn.py

# Integration Tests
python src/tests/test_integration.py
```

### 4. Run Load Tests

Execute load tests for performance analysis:

```bash
# Install k6 if not already installed
# Windows: winget install k6
# macOS: brew install k6
# Linux: snap install k6

# Run upload load tests
cd load_tests
k6 run scenarios/upload_test.js

# Run streaming load tests
k6 run scenarios/streaming_test.js

# Run concurrent viewers test
k6 run scenarios/concurrent_test.js
```

### 5. View Results

Access various dashboards and results:

```bash
# Open Grafana Dashboard (credentials: admin/admin)
open http://localhost:3000

# View Service Health Endpoints
curl http://localhost:8001/health  # HTTP/2 Upload
curl http://localhost:8002/health  # Chunked Upload
curl http://localhost:8003/health  # Streaming
curl http://localhost:8004/health  # CDN Edge

# View Test Reports
open load_tests/reports/  # Load test results
open docs/ANALYSIS_REPORT.md  # Performance analysis
```

### 6. Clean Up

When finished testing:

```bash
# Stop all services
docker-compose down

# Clean up test data
docker-compose down -v  # Also removes volumes
rm -rf uploads/*       # Clean local upload directory
```

### Troubleshooting

If tests fail:

1. Check service health:
   ```bash
   docker-compose ps
   docker-compose logs -f  # Follow all logs
   ```

2. Verify infrastructure:
   ```bash
   # Check PostgreSQL
   docker-compose exec postgres psql -U videouser -d video_streaming -c "\dt"

   # Check Redis
   docker-compose exec redis redis-cli ping

   # Check RabbitMQ
   docker-compose exec rabbitmq rabbitmqctl list_queues
   ```

3. Reset and retry:
   ```bash
   docker-compose down -v
   docker-compose up -d
   ```

For more details on testing and performance analysis, see [ANALYSIS_REPORT.md](docs/ANALYSIS_REPORT.md).

## License

MIT License - See LICENSE for details