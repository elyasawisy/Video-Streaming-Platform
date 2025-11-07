```mermaid
xychart-beta
    title "Upload Performance Under Load"
    x-axis [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    y-axis "Average Upload Time (s)" 0 --> 300
    line [50, 75, 100, 140, 180, 210, 235, 255, 280, 295] "HTTP/2"
    line [45, 65, 85, 110, 140, 165, 185, 200, 215, 220] "Chunked"
```