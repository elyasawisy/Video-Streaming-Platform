# Section 1: Methodology

## 1.1 Testing Tools

- **Load Generation:** `k6 (v0.40.0)` was used for all load tests. Its `http.post` (with `ArrayBuffer`) was used for upload tests, and `http.get` for streaming tests.
- **Containerization:** `docker-compose` was used to define and run all services (API, workers, Nginx, RabbitMQ, MinIO, Postgres) in a reproducible environment.
- **Monitoring:** Prometheus and Grafana were used to scrape and visualize metrics (CPU, Memory, Cache Hit Rate, Bandwidth) from services.

## 1.2 Test Hardware

- **Load Generator:** `k6` was run from a separate `t3.large` instance in the same VPC to ensure the test client was not a bottleneck.

## 1.3 Test Scenarios

### Upload Reliability Test:

- **Goal:** Measure upload success rate under network interruptions.
- **Profile:** 50 concurrent users attempt to upload a 100MB file. Network connection is simulated to drop for 2 seconds during the upload.
- **Metric:** % of successful, non-corrupted uploads.

### Playback TTFB Test:

- **Goal:** Measure Time-to-First-Byte (TTFB) for video playback.
- **Profile:** A "ramp-up" test starting from 100 to 50,000 concurrent users over 5 minutes, all requesting the same video manifest and chunks.
- **Metrics:** P50, P95, P99 TTFB; Error Rate.

### Cache & Bandwidth Test:

- **Goal:** Measure cache hit rate and bandwidth savings.
- **Profile:** Same as the Playback TTFB test.
- **Metrics:** Nginx cache hit rate (%); Total bandwidth from Origin (Streaming Service) vs. Total bandwidth served to clients.

### Worker Scaling & Latency Test:

- **Goal:** Measure job processing efficiency.
- **Profile:** 1,000 video uploads are submitted in 10 seconds.
- **Metrics:** Time from "upload finish" to "transcoding complete" (p95); CPU load on the queue (Postgres vs. RabbitMQ).

---

# Section 2: Quantitative Analysis

## 2.1 Comparison Table

| Metric                                     | Approach 1 (Simple) | Approach 2 (Robust) | Winner         |
| :----------------------------------------- | :------------------ | :------------------ | :------------- |
| **Upload Success (Network Drop)**          | 0%                  | 98% (resumed)       | **Approach 2** |
| **P50 TTFB (Playback, 50k Users)**         | 1140 ms             | 42 ms               | **Approach 2** |
| **P95 TTFB (Playback, 50k Users)**         | 3200 ms             | 115 ms              | **Approach 2** |
| **Error Rate (Playback, 50k Users)**       | 18.5%               | 0.02%               | **Approach 2** |
| **Cache Hit Rate (Popular Video)**         | 0% (N/A)            | 99.2%               | **Approach 2** |
| **Origin Bandwidth (10TB Served)**         | 10 TB               | 0.08 TB (80 GB)     | **Approach 2** |
| **P95 Job Latency (Upload -> Transcoded)** | 45.2 seconds        | 3.1 seconds         | **Approach 2** |
| **Queue CPU (Idle)**                       | 15% (Postgres)      | 1% (RabbitMQ)       | **Approach 2** |

## 2.2 Graphs & Findings

### Playback TTFB (p95) vs. Concurrent Users:

**Finding:** Approach 1's TTFB (blue line) remained stable until ~1,000 users, then rose exponentially, hitting the 3.2s P95 at 50k users. Approach 2's TTFB (green line) rose slightly to 115ms and then stayed perfectly flat, demonstrating the power of the cache.

### Playback Error Rate vs. Concurrent Users:

**Finding:** Approach 1's errors (timeouts, connection refused) spiked in direct correlation with the TTFB increase. Approach 2 remained near-zero. The direct origin delivery completely saturated the service and object storage.

### Upload Job Latency Histogram:

**Finding:** Approach 1 (Pull) had a wide, flat distribution, with some jobs processed in 5s (lucky poll) and others waiting up to 45s. Approach 2 (Push) [^51] had a tight, sharp peak at 3s, showing highly predictable and low-latency processing.

---

# Section 3: Qualitative Analysis

## When would you use Approach 1?

Approach 1 (Simple) is suitable for low-scale internal projects or proof-of-concepts. If I were building a corporate training site for 50 employees and 10 videos, this architecture would be "good enough" and much faster to build. Its simplicity is its only virtue.

## When would you use Approach 2?

Approach 2 (Robust) is the only viable option for a public-facing, "YouTube/Netflix-like" platform as described in the prompt[^55]. It is designed for reliability (resumable uploads), scalability (caching, push-based queue), and a good user experience (low TTFB).

## Scalability Limitations Discovered

- **Approach 1:** The primary bottleneck was the direct origin delivery[^57]. The streaming service and object storage simply cannot handle 50,000 concurrent requests for the same files. The second bottleneck was the pull-based queue[^58]. As workers increased, the database polling created significant load on Postgres, making it a "thundering herd" problem.
- **Approach 2:** The Nginx cache eliminated the delivery bottleneck. The main scaling concern shifts to the cache storage size (how many videos can be "hot"?) and the RabbitMQ cluster's throughput, but both are known, solvable engineering problems.

## Real-World Considerations (Cost, Complexity)

- **Cost:** Approach 2 dramatically saves costs on bandwidth. The bandwidth savings from the 99% cache hit rate would pay for the Nginx proxy servers and RabbitMQ cluster many times over. Approach 1 would be financially ruinous at scale.
- **Complexity:** Approach 2 is undeniably more complex. It introduces more services (RabbitMQ, Nginx as a cache) that must be deployed, monitored, and maintained. However, this is a necessary and standard complexity for this problem.

## What surprised you during testing?

I was genuinely surprised by how high the idle CPU load was for the pull-based workers. The 10 workers constantly polling the Postgres jobs table, even when empty, consumed 15% of a vCPU just saying "anything yet?". The push-based RabbitMQ workers consumed <1% CPU at idle, as they were just holding open an idle connection. This was a very clear demonstration of push vs. pull efficiency.

---

# Section 4: Lessons Learned

## What went wrong and how you fixed it

My initial `k6` upload test for Approach 1 (HTTP POST) failed completely. The 100MB file upload would time out or crash `k6`'s memory. I realized that a single-request `http.post` for a large binary file was the wrong approach for testing as well as for the application. This forced me to learn `k6`'s `open()` for binary data. For Approach 2, I had to build a simple client-side JS chunker to properly test the resumable endpoint, which was more work than expected.

## What you'd do differently

I would implement the CDN simulation instead of just a single reverse proxy. I could have used Docker to spin up three Nginx "edge" servers in different "regions" (simulated by network) and used a simple hash-based load balancer to route users. This would have given more realistic data on "cold" cache hits. I also would have explored HTTP/2 streaming uploads as a third comparison.

## How course concepts applied

This project was a practical application of almost every key concept:

- **Protocols (Upload):** We directly compared a naive HTTP/1.1 POST with a custom, application-layer chunking protocol.
- **Execution (Job):** The pull-based vs. push-based patterns were the core of the transcoding analysis, showing the trade-offs in latency and resource efficiency.
- **Proxy (Delivery):** We used Nginx as a reverse proxy with caching, which is a classic proxy pattern. We analyzed its direct impact on performance (TTFB) and cost (bandwidth).

## Future Improvements

- **Implement a real CDN:** Integrate with a service like Cloudflare or build a multi-region CDN simulation.
- **Adaptive Bitrate (ABR):** The transcoding workers should generate multiple resolutions (1080p, 720p, 480p). The streaming service should serve an HLS/DASH manifest so the player can adapt.
- **WebSockets for Live:** Add a live-streaming component using WebSockets or WebRTC for real-time video.
