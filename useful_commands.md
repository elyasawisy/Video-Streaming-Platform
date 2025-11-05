## Service Management

### Start services
docker-compose up -d

### Stop services
docker-compose down

### View service status
docker-compose ps

### Restart specific service
docker-compose restart upload_service_http2

### Rebuild and restart
docker-compose up -d --build upload_service_http2

## Logs & Debugging

### View all logs
docker-compose logs -f

### View specific service logs
docker-compose logs -f upload_service_http2
docker-compose logs -f rabbitmq

### View last 100 lines
docker-compose logs --tail=100 upload_service_http2

## Database Operations

### Connect to PostgreSQL
docker-compose exec postgres psql -U videouser -d video_streaming

### List videos
SELECT id, title, status, file_size, upload_method, created_at 
FROM videos 
ORDER BY created_at DESC 
LIMIT 10;

### Check upload metrics
SELECT 
    upload_method,
    COUNT(*) as count,
    AVG(upload_duration) as avg_duration_ms,
    AVG(throughput) as avg_throughput_bps
FROM upload_metrics
GROUP BY upload_method;

### Check chunked uploads
SELECT * FROM chunked_uploads ORDER BY created_at DESC LIMIT 10;

### Delete test data
DELETE FROM videos WHERE uploader_id LIKE 'test%';
DELETE FROM chunked_uploads WHERE video_id IN (
    SELECT id FROM videos WHERE uploader_id LIKE 'test%'
);

## RabbitMQ Operations

### Check queue status
docker-compose exec rabbitmq rabbitmqctl list_queues

### Purge queue
docker-compose exec rabbitmq rabbitmqctl purge_queue transcode_queue

### RabbitMQ Management UI
http://localhost:15672
Login: guest/guest

## Redis Operations

### Connect to Redis
docker-compose exec redis redis-cli

### Check all keys
KEYS *

### Check chunk keys for upload
KEYS chunk:UPLOAD_ID:*

### Clear all chunk keys
redis-cli KEYS "chunk:*" | xargs redis-cli DEL

## Testing

### Quick upload test (HTTP/2)
curl -X POST http://localhost:8001/api/v1/upload \
  -F "video=@test.mp4" \
  -F "title=Quick Test" \
  -F "uploader_id=curl-test"

### Check video status
curl http://localhost:8001/api/v1/videos/VIDEO_ID | jq

### List all videos
curl http://localhost:8001/api/v1/videos | jq

### Get metrics
curl http://localhost:8001/api/v1/metrics | jq
curl http://localhost:8002/api/v1/metrics | jq

## Performance Testing

### Generate test file
dd if=/dev/urandom of=test_100mb.mp4 bs=1M count=100

### Run load test with Apache Bench
ab -n 100 -c 10 -p test.mp4 -T multipart/form-data http://localhost:8001/api/v1/upload

### Monitor resource usage
docker stats

### Check disk usage
du -sh uploads/*

## Troubleshooting

### Service won't start
docker-compose logs upload_service_http2
docker-compose restart upload_service_http2

### Port already in use
lsof -i :8001
# Kill the process or change port in docker-compose.yml

### Database connection issues
docker-compose restart postgres
docker-compose logs postgres

### Clear all data and restart
docker-compose down -v
docker-compose up -d

### Check file permissions
ls -la uploads/
chmod -R 777 uploads/  # For development only!

## Monitoring

### Watch service logs in real-time
watch -n 1 'docker-compose ps'

### Monitor upload directory size
watch -n 5 'du -sh uploads/*'

### Check system resources
htop
iotop

## Network Issues

### Test connectivity
curl http://localhost:8001/health
telnet localhost 8001

### Check Docker network
docker network ls
docker network inspect video-streaming-platform_default