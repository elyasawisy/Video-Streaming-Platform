```mermaid
graph TB
    subgraph Client Layer
        C[Client] --> U1[HTTP/2 Upload]
        C --> U2[Chunked Upload]
        C --> VS[Video Streaming]
    end

    subgraph Load Balancers
        U1 --> LB[NGINX/HAProxy]
        U2 --> LB
        VS --> LB
    end

    subgraph Upload Services
        LB --> US1[Upload Service HTTP/2]
        LB --> US2[Upload Service Chunked]
    end

    subgraph Storage
        US1 --> TS[Temp Storage]
        US2 --> TS
        TS --> PS[Permanent Storage]
    end

    subgraph Message Queue
        US1 --> RMQ[RabbitMQ]
        US2 --> RMQ
    end

    subgraph Workers
        RMQ --> W1[Pull Worker 1]
        RMQ --> W2[Pull Worker 2]
        RMQ --> W3[Push Worker 1]
        RMQ --> W4[Push Worker 2]
    end

    subgraph Databases
        US1 --> DB[(PostgreSQL)]
        US2 --> DB
        US1 --> RC[(Redis Cache)]
        US2 --> RC
    end

    subgraph CDN Layer
        W1 --> CDN1[Edge Server 1]
        W2 --> CDN1
        W3 --> CDN2[Edge Server 2]
        W4 --> CDN2
    end

    subgraph Monitoring
        PROM[Prometheus] --> |Scrape| US1
        PROM --> |Scrape| US2
        PROM --> |Scrape| W1
        PROM --> |Scrape| W2
        PROM --> |Scrape| W3
        PROM --> |Scrape| W4
        PROM --> GRAF[Grafana]
    end

    CDN1 --> VS
    CDN2 --> VS

┌─────────────┐
│   Client    │
└──────┬──────┘
       │
       ├──────────┐
       │          │
   HTTP/2      Chunked
   Upload      Upload
       │          │
       v          v
┌──────────────────────┐
│  Upload Services     │
│  (Flask + Hypercorn) │
└──────────┬───────────┘
           │
           v
    ┌──────────────┐
    │  PostgreSQL  │
    │  (Metadata)  │
    └──────────────┘
           │
           v
    ┌──────────────┐
    │  RabbitMQ    │
    │  (Job Queue) │
    └──────┬───────┘
           │
       ┌───┴────┐
       │        │
    Pull      Push
   Workers   Workers
       │        │
       └───┬────┘
           │
           v
    ┌──────────────┐
    │  Transcoded  │
    │  Videos      │
    └──────┬───────┘
           │
           v
    ┌──────────────────┐
    │ Streaming Service│
    │ (Flask + Redis)  │
    └──────┬───────────┘
           │
       ┌───┴────┐
       │        │
    Reverse   CDN
     Proxy    Edge
    Caching  Servers
       │        │
       └───┬────┘
           │
           v
    ┌──────────────┐
    │    Client    │
    │   (Viewer)   │
    └──────────────┘

    gRPC ←──────────→ (Cross-service communication)
```