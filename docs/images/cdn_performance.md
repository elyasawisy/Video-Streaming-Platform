```mermaid
xychart-beta
    title "Content Delivery Response Times"
    x-axis [1000, 5000, 10000, 20000, 30000, 40000, 50000]
    y-axis "TTFB (ms)" 0 --> 500
    line [25, 35, 45, 65, 95, 140, 200] "Edge Cache"
    line [85, 120, 160, 220, 300, 400, 480] "Reverse Proxy"
```