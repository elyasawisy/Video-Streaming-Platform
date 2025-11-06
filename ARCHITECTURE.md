# 1. Overview

This document details the system architecture for the Video Streaming Platform project. The goal is to build a system capable of handling large file uploads, transcoding jobs, and streaming to a large number of concurrent viewers.

To meet the project's comparative analysis requirement, We have designed two distinct architectures:

- **Approach 1 (Simple/Monolithic):** A baseline implementation using simple, direct approaches.

  - **Upload:** Standard HTTP/1.1 POST.
  - **Job Processing:** Pull-based workers polling a queue.
  - **Delivery:** Direct origin server delivery.

- **Approach 2 (Robust/Distributed):** A production-oriented implementation using more resilient and scalable patterns.
  - **Upload:** Chunked file upload with resumability.
  - **Job Processing:** Push-based pub-sub pattern.
  - **Delivery:** Reverse proxy with caching.

---

# 2. System Architecture Diagrams

## Approach 1: Simple Architecture

**Description:**
In this setup, the user's browser sends a single, large HTTP POST request directly to the API Gateway (Nginx). Nginx forwards this to the Upload Service. The Upload Service saves the entire file to disk and then writes a "new-video" job entry into a PostgreSQL database table (acting as a simple queue).

Transcoding Workers constantly poll this table (`SELECT ... FOR UPDATE SKIP LOCKED`). When a worker finds a job, it transcodes the video and saves the chunks to Object Storage (MinIO).

For playback, the viewer's request hits the Streaming Service, which reads the video chunks directly from the Object Storage and serves them.

## Approach 2: Robust Architecture

**Description:**
The user's browser communicates with a Chunking Service (part of the API) to upload the file in small, resumable parts. Once all chunks are received and verified, the Chunking Service reassembles the file and publishes a message to a RabbitMQ topic (e.g., `video.uploaded`).

This message is pushed to a Transcoding Queue. Transcoding Workers (as part of a consumer group) receive this push-based job, perform the transcoding, and store the resulting HLS/DASH chunks in Object Storage (MinIO).

For playback, the viewer's request first hits a Reverse Proxy (Nginx). Nginx checks its local cache.

- **Cache Hit:** The chunk is served immediately from the proxy's fast disk.
- **Cache Miss:** Nginx forwards the request to the Streaming Service, which fetches the chunk from Object Storage. Nginx then caches this chunk and serves it to the user.

---

# 3. OSI Model Protocol Breakdown

Our system primarily operates at the Application, Presentation, Transport, and Network layers.

| OSI Layer                  | Protocol(s) Used  | Description                                                                                                                         |
| :------------------------- | :---------------- | :---------------------------------------------------------------------------------------------------------------------------------- |
| **Layer 7 (Application)**  | HTTP/1.1, HTTP/2  | Used for all client-server communication: file uploads, API calls, and video chunk requests.                                        |
|                            | AMQP (RabbitMQ)   | Used in Approach 2 for push-based job queuing between the Upload Service and Transcoding Workers.                                   |
| **Layer 6 (Presentation)** | TLS/SSL (Assumed) | Encrypts all HTTP traffic (HTTPS) to secure data in transit.                                                                        |
|                            | JSON              | Standard format for API request/response bodies.                                                                                    |
|                            | H.264, AAC        | Video/audio codecs used after transcoding. The system transports this data.                                                         |
| **Layer 4 (Transport)**    | TCP               | The underlying transport for HTTP and AMQP. Provides reliable, ordered delivery, which is essential for file uploads and API calls. |
| **Layer 3 (Network)**      | IP                | Handles the logical addressing and routing of packets between the user, our servers, and storage.                                   |

---

# 4. Sequence Diagrams

## Flow 1: Video Upload & Transcoding

**Approach 1 (Pull-based):**

1.  `Client -> API Gateway`: `POST /upload` (with large 1GB file).
2.  `API Gateway -> Upload Service`: Forwards the entire request.
3.  `Upload Service`: Spends 30s-2min receiving the full file.
4.  `Upload Service -> DB`: `INSERT INTO jobs (video_id, status) VALUES ('v1', 'pending')`.
5.  `Transcoding Worker (polling)`: `SELECT * FROM jobs WHERE status = 'pending' LIMIT 1 ...`
6.  `DB -> Transcoding Worker`: Returns the 'v1' job.
7.  `Transcoding Worker`: Transcodes file, saves chunks to Object Storage.
8.  `Transcoding Worker -> DB`: `UPDATE jobs SET status = 'complete' WHERE video_id = 'v1'`.

**Approach 2 (Push-based & Chunked):**

1.  `Client -> Upload Service`: `POST /upload/init` (with file name, size).
2.  `Upload Service -> Client`: Returns `upload_id`.
3.  `Client -> Upload Service`: `POST /upload/chunk?upload_id=...&chunk=1` (with 2MB data).
4.  ... (Client repeats this 500 times) ...
5.  `Client -> Upload Service`: `POST /upload/finish?upload_id=...`
6.  `Upload Service`: Verifies all chunks, reassembles the file.
7.  `Upload Service -> RabbitMQ`: Publishes message `{"video_id": "v2"}` to `video.uploaded` exchange.
8.  `RabbitMQ -> Transcoding Worker`: Pushes the job message immediately to a listening worker.
9.  `Transcoding Worker`: Transcodes file, saves chunks to Object Storage.

## Flow 2: Video Playback

**Approach 1 (Direct Delivery):**

1.  `Client -> Streaming Service`: `GET /play/v1/segment_1.ts`.
2.  `Streaming Service -> Object Storage`: `GET segment_1.ts`.
3.  `Object Storage -> Streaming Service`: Returns file chunk.
4.  `Streaming Service -> Client`: Returns file chunk.
    _(This happens for every single chunk, for every single user)._

**Approach 2 (Cached Delivery):**

1.  `Client -> Nginx Proxy`: `GET /play/v1/segment_1.ts`.
2.  `Nginx Proxy`: Checks local cache for `segment_1.ts`.
3.  **(Cache Miss):**
    1.  `Nginx Proxy -> Streaming Service`: `GET /play/v1/segment_1.ts`.
    2.  `Streaming Service -> Object Storage`: `GET segment_1.ts`.
    3.  `Object Storage -> Streaming Service`: Returns chunk.
    4.  `Streaming Service -> Nginx Proxy`: Returns chunk.
    5.  `Nginx Proxy`: Saves chunk to cache and returns it to Client.
4.  **(Cache Hit - next user):**
    1.  `Client 2 -> Nginx Proxy`: `GET /play/v1/segment_1.ts`.
    2.  `Nginx Proxy`: Finds `segment_1.ts` in cache.
    3.  `Nginx Proxy -> Client 2`: Returns chunk immediately.

---

# 5. Design Decisions & Trade-offs

| Feature       | Approach 1 (Simple)      | Approach 2 (Robust)    | Trade-off Justification                                                                                                                                                                                                                                                |
| :------------ | :----------------------- | :--------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Upload**    | HTTP/1.1 POST            | Chunked Upload         | HTTP POST is simple but unreliable for large files and poor networks. A single packet drop can fail the entire upload. Chunking is complex but provides **resumability and reliability**, which is non-negotiable for a good user experience.                          |
| **Job Queue** | Pull-based (SQL polling) | Push-based (RabbitMQ)  | Polling is easy to implement but inefficient. It wastes DB resources and adds latency (worker only finds the job on its next poll). A **push-based pub-sub system** (RabbitMQ) delivers jobs instantly and scales horizontally with low overhead.                      |
| **Delivery**  | Direct from Origin       | Reverse Proxy Cache    | Direct delivery is a bottleneck. The streaming service and object storage will be overwhelmed. A caching proxy (Nginx) serves popular content from its own fast storage, dramatically **reducing TTFB**, **saving origin bandwidth**, and protecting backend services. |
| **Storage**   | MinIO (Object Storage)   | MinIO (Object Storage) | MinIO was chosen for both as an S3-compatible local/containerized object store. This is a standard pattern for storing large, unstructured data like video.                                                                                                            |
