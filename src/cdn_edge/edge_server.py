"""Enhanced CDN Edge Server with improved caching, rate limiting and request validation."""

import os
import re
import time
import hashlib
import logging
import functools
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any
from flask import Flask, request, Response, jsonify, make_response
import requests
import redis
from collections import OrderedDict
from dataclasses import dataclass
from prometheus_client import Counter, Histogram, start_http_server

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('edge_server.log')
    ]
)
logger = logging.getLogger(__name__)

# Prometheus metrics
REQUESTS = Counter('cdn_requests_total', 'Total requests', ['path', 'method', 'status'])
CACHE_HITS = Counter('cdn_cache_hits_total', 'Cache hits', ['type'])
CACHE_MISSES = Counter('cdn_cache_misses_total', 'Cache misses', ['type'])
RESPONSE_TIME = Histogram('cdn_response_time_seconds', 'Response time in seconds')
BYTES_SERVED = Counter('cdn_bytes_served_total', 'Total bytes served', ['cache_status'])
RATE_LIMITS = Counter('cdn_rate_limits_total', 'Rate limit hits', ['ip'])

@dataclass
class VideoMetadata:
    """Video metadata for validation."""
    id: str
    size: int
    mime_type: str
    duration: int
    qualities: list
    created_at: datetime

# Configuration
class Config:
    """Enhanced configuration with security and performance settings."""
    # Edge identification
    EDGE_ID = os.getenv('EDGE_ID', 'edge-1')
    EDGE_LOCATION = os.getenv('EDGE_LOCATION', 'US-East')
    EDGE_CAPACITY = os.getenv('EDGE_CAPACITY', 'standard')  # standard/high/premium

    # Service URLs
    ORIGIN_URL = os.getenv('ORIGIN_URL', 'http://streaming_service:8003')
    REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379')
    METRICS_PORT = int(os.getenv('METRICS_PORT', '9100'))

    # Cache configuration
    CACHE_DIR = os.getenv('CACHE_DIR', './cache')
    MAX_CACHE_SIZE_GB = int(os.getenv('MAX_CACHE_SIZE_GB', 10))
    CHUNK_SIZE = 1024 * 1024  # 1MB chunks
    CACHE_TTL = int(os.getenv('CACHE_TTL', 3600))  # 1 hour default
    CACHE_WARMUP = os.getenv('CACHE_WARMUP', 'false').lower() == 'true'
    POPULAR_THRESHOLD = int(os.getenv('POPULAR_THRESHOLD', 100))

    # Rate limiting
    RATE_LIMIT_ENABLED = os.getenv('RATE_LIMIT_ENABLED', 'true').lower() == 'true'
    RATE_LIMIT_DEFAULT = int(os.getenv('RATE_LIMIT_DEFAULT', '100'))  # requests per minute
    RATE_LIMIT_BURST = int(os.getenv('RATE_LIMIT_BURST', '20'))  # burst size
    RATE_LIMIT_PREMIUM = int(os.getenv('RATE_LIMIT_PREMIUM', '1000'))  # premium tier limit

    # Security
    ALLOWED_QUALITIES = ['360p', '480p', '720p', '1080p', 'original']
    ALLOWED_MIME_TYPES = ['video/mp4', 'video/webm']
    MAX_REQUEST_SIZE = 1024 * 1024  # 1MB
    API_KEY_HEADER = 'X-API-Key'
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', '*').split(',')

    # Timeouts and retries
    ORIGIN_TIMEOUT = int(os.getenv('ORIGIN_TIMEOUT', 30))
    REDIS_TIMEOUT = int(os.getenv('REDIS_TIMEOUT', 5))
    RETRY_ATTEMPTS = int(os.getenv('RETRY_ATTEMPTS', 3))
    RETRY_BACKOFF = int(os.getenv('RETRY_BACKOFF', 1))

    # Monitoring
    HEALTH_CHECK_INTERVAL = int(os.getenv('HEALTH_CHECK_INTERVAL', 60))
    METRICS_ENABLED = os.getenv('METRICS_ENABLED', 'true').lower() == 'true'

class RateLimiter:
    """Enhanced rate limiter with Redis backend and tiered limits."""
    def __init__(self, redis_client):
        self.redis = redis_client
        self.default_limit = Config.RATE_LIMIT_DEFAULT
        self.premium_limit = Config.RATE_LIMIT_PREMIUM
        self.burst = Config.RATE_LIMIT_BURST
        self.window = 60  # 1 minute window

    def _get_limit_key(self, ip: str) -> str:
        """Generate Redis key for rate limiting."""
        return f"ratelimit:{Config.EDGE_ID}:{ip}"

    def _get_tier(self, api_key: Optional[str]) -> Tuple[int, int]:
        """Get rate limit tier based on API key."""
        if not api_key:
            return self.default_limit, self.burst

        # TODO: Implement proper API key validation
        if api_key.startswith('premium_'):
            return self.premium_limit, self.burst * 2
        return self.default_limit, self.burst

    def is_allowed(self, ip: str, api_key: Optional[str] = None) -> bool:
        """Check if request is allowed under rate limits."""
        if not Config.RATE_LIMIT_ENABLED:
            return True

        limit, burst = self._get_tier(api_key)
        key = self._get_limit_key(ip)
        pipe = self.redis.pipeline()

        try:
            now = time.time()
            cleanup_before = now - self.window

            # Cleanup old requests
            pipe.zremrangebyscore(key, 0, cleanup_before)
            
            # Count requests in current window
            pipe.zcount(key, cleanup_before, now)
            
            # Add current request
            pipe.zadd(key, {str(now): now})
            
            # Set expiry
            pipe.expire(key, self.window)
            
            # Execute pipeline
            _, count, *_ = pipe.execute()

            # Check if under limit
            allowed = count <= limit
            if not allowed:
                RATE_LIMITS.labels(ip=ip).inc()

            return allowed

        except redis.RedisError as e:
            logger.error(f"Rate limit error: {e}")
            return True  # Allow on error

    def get_remaining(self, ip: str, api_key: Optional[str] = None) -> Tuple[int, int]:
        """Get remaining requests and reset time."""
        if not Config.RATE_LIMIT_ENABLED:
            return -1, 0

        limit, _ = self._get_tier(api_key)
        key = self._get_limit_key(ip)

        try:
            now = time.time()
            cleanup_before = now - self.window
            count = self.redis.zcount(key, cleanup_before, now)
            ttl = self.redis.ttl(key)

            return max(0, limit - count), ttl if ttl > 0 else self.window

        except redis.RedisError as e:
            logger.error(f"Rate limit error: {e}")
            return 0, 0

# Initialize Redis clients
try:
    redis_client = redis.from_url(
        Config.REDIS_URL,
        socket_timeout=Config.REDIS_TIMEOUT,
        retry_on_timeout=True
    )
    rate_limiter = RateLimiter(redis_client)
    logger.info(f"Connected to Redis: {Config.REDIS_URL}")
except redis.RedisError as e:
    logger.error(f"Redis connection error: {e}")
    raise

# Initialize metrics server if enabled
if Config.METRICS_ENABLED:
    try:
        start_http_server(Config.METRICS_PORT)
        logger.info(f"Started metrics server on port {Config.METRICS_PORT}")
    except Exception as e:
        logger.error(f"Failed to start metrics server: {e}")

# Flask app setup
app = Flask(__name__)

class EdgeServerError(Exception):
    """Base exception for edge server errors."""
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code

def error_response(error: str, status_code: int = 500) -> Response:
    """Create standardized error response."""
    response = jsonify({
        'error': error,
        'edge_id': Config.EDGE_ID,
        'timestamp': datetime.utcnow().isoformat()
    })
    response.status_code = status_code
    return response

def validate_request(f):
    """Validate common request parameters and headers."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            # Rate limiting
            api_key = request.headers.get(Config.API_KEY_HEADER)
            if not rate_limiter.is_allowed(request.remote_addr, api_key):
                remaining, reset = rate_limiter.get_remaining(request.remote_addr, api_key)
                response = error_response('Rate limit exceeded', 429)
                response.headers['X-RateLimit-Remaining'] = str(remaining)
                response.headers['X-RateLimit-Reset'] = str(reset)
                return response

            # Request size validation
            content_length = request.content_length or 0
            if content_length > Config.MAX_REQUEST_SIZE:
                return error_response('Request too large', 413)

            # CORS validation
            origin = request.headers.get('Origin')
            if origin and Config.CORS_ORIGINS != ['*']:
                if origin not in Config.CORS_ORIGINS:
                    return error_response('CORS not allowed', 403)

            return f(*args, **kwargs)

        except Exception as e:
            logger.error(f"Request validation error: {e}")
            return error_response('Invalid request', 400)

    return wrapper

def validate_video_request(f):
    """Validate video-specific parameters."""
    @functools.wraps(f)
    def wrapper(video_id, *args, **kwargs):
        try:
            # Validate quality parameter
            quality = request.args.get('quality', '720p')
            if quality not in Config.ALLOWED_QUALITIES:
                return error_response(f'Invalid quality. Allowed: {Config.ALLOWED_QUALITIES}', 400)

            # Get video metadata from Redis
            metadata_key = f'video:{video_id}'
            metadata = redis_client.hgetall(metadata_key)

            if not metadata:
                # Fetch from origin if not in cache
                try:
                    info_url = f"{Config.ORIGIN_URL}/api/v1/videos/{video_id}/info"
                    response = requests.get(info_url, timeout=Config.ORIGIN_TIMEOUT)
                    if response.status_code == 404:
                        return error_response('Video not found', 404)
                    if response.status_code != 200:
                        return error_response('Failed to fetch video info', 502)

                    video_info = response.json()
                    metadata = {
                        'size': str(video_info.get('file_size', 0)),
                        'mime_type': video_info.get('mime_type', ''),
                        'duration': str(video_info.get('duration', 0)),
                        'qualities': ','.join(video_info.get('quality_available', [])),
                        'created_at': video_info.get('created_at', '')
                    }
                    
                    # Cache metadata
                    redis_client.hmset(metadata_key, metadata)
                    redis_client.expire(metadata_key, Config.CACHE_TTL)

                except requests.exceptions.RequestException as e:
                    logger.error(f"Failed to fetch video info: {e}")
                    return error_response('Origin server error', 502)

            # Validate metadata
            if metadata.get('mime_type') not in Config.ALLOWED_MIME_TYPES:
                return error_response('Unsupported video format', 400)

            if quality not in metadata.get('qualities', '').split(','):
                return error_response(f'Quality {quality} not available', 400)

            # Store metadata in request context
            request.video_metadata = VideoMetadata(
                id=video_id,
                size=int(metadata.get('size', 0)),
                mime_type=metadata.get('mime_type', ''),
                duration=int(metadata.get('duration', 0)),
                qualities=metadata.get('qualities', '').split(','),
                created_at=datetime.fromisoformat(metadata.get('created_at', datetime.utcnow().isoformat()))
            )

            return f(video_id, *args, **kwargs)

        except ValueError as e:
            logger.error(f"Validation error for video {video_id}: {e}")
            return error_response('Invalid video metadata', 400)
        except Exception as e:
            logger.error(f"Unexpected error validating video {video_id}: {e}")
            return error_response('Internal server error', 500)

    return wrapper

@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors."""
    return error_response('Not found', 404)

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"Internal server error: {error}")
    return error_response('Internal server error', 500)

@app.after_request
def after_request(response):
    """Add common headers and log request."""
    # Add common headers
    response.headers['Server'] = f'CDN-Edge/{Config.EDGE_ID}'
    response.headers['X-Edge-Location'] = Config.EDGE_LOCATION
    
    # Add CORS headers if enabled
    if Config.CORS_ORIGINS == ['*']:
        response.headers['Access-Control-Allow-Origin'] = '*'
    elif request.headers.get('Origin') in Config.CORS_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = request.headers['Origin']
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Range'
        response.headers['Access-Control-Expose-Headers'] = 'Content-Range, Accept-Ranges'
    
    # Add rate limit headers
    if Config.RATE_LIMIT_ENABLED:
        remaining, reset = rate_limiter.get_remaining(
            request.remote_addr,
            request.headers.get(Config.API_KEY_HEADER)
        )
        response.headers['X-RateLimit-Remaining'] = str(remaining)
        response.headers['X-RateLimit-Reset'] = str(reset)
    
    # Update metrics
    REQUESTS.labels(
        path=request.path,
        method=request.method,
        status=response.status_code
    ).inc()
    
    return response

class LRUCache:
    """LRU Cache implementation for video files"""
    
    def __init__(self, cache_dir: str, max_size_bytes: int):
        self.cache_dir = cache_dir
        self.max_size_bytes = max_size_bytes
        self.current_size = 0
        self.access_order = OrderedDict()  # key -> last_access_time
        
        # Create cache directory
        os.makedirs(cache_dir, exist_ok=True)
        
        # Load existing cache
        self._load_cache_state()
    
    def _load_cache_state(self):
        """Load cache state from disk"""
        if os.path.exists(self.cache_dir):
            for filename in os.listdir(self.cache_dir):
                filepath = os.path.join(self.cache_dir, filename)
                if os.path.isfile(filepath):
                    size = os.path.getsize(filepath)
                    self.current_size += size
                    # Use file modification time as last access
                    mtime = os.path.getmtime(filepath)
                    self.access_order[filename] = mtime
        
        logger.info(
            f"[{Config.EDGE_ID}] Loaded cache: "
            f"{len(self.access_order)} files, "
            f"{self.current_size / 1024 / 1024:.2f} MB"
        )
    
    def _get_cache_key(self, video_id: str, quality: str, start: int, end: int) -> str:
        """Generate cache key for video chunk"""
        # Use hash to avoid long filenames
        key_data = f"{video_id}:{quality}:{start}:{end}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def _evict_lru(self, needed_space: int):
        """Evict least recently used items to make space"""
        while self.current_size + needed_space > self.max_size_bytes and self.access_order:
            # Get LRU item
            lru_key = next(iter(self.access_order))
            filepath = os.path.join(self.cache_dir, lru_key)
            
            if os.path.exists(filepath):
                size = os.path.getsize(filepath)
                os.remove(filepath)
                self.current_size -= size
                logger.info(f"[{Config.EDGE_ID}] Evicted: {lru_key} ({size / 1024:.2f} KB)")
            
            del self.access_order[lru_key]
    
    def get(self, video_id: str, quality: str, start: int, end: int):
        """Get cached chunk"""
        cache_key = self._get_cache_key(video_id, quality, start, end)
        filepath = os.path.join(self.cache_dir, cache_key)
        
        if os.path.exists(filepath):
            # Update access time
            self.access_order.move_to_end(cache_key)
            self.access_order[cache_key] = time.time()
            
            logger.info(f"[{Config.EDGE_ID}] Cache HIT: {video_id} ({quality}) {start}-{end}")
            
            with open(filepath, 'rb') as f:
                return f.read()
        
        logger.info(f"[{Config.EDGE_ID}] Cache MISS: {video_id} ({quality}) {start}-{end}")
        return None
    
    def put(self, video_id: str, quality: str, start: int, end: int, data: bytes):
        """Store chunk in cache"""
        cache_key = self._get_cache_key(video_id, quality, start, end)
        filepath = os.path.join(self.cache_dir, cache_key)
        
        data_size = len(data)
        
        # Evict if needed
        self._evict_lru(data_size)
        
        # Store chunk
        try:
            with open(filepath, 'wb') as f:
                f.write(data)
            
            self.current_size += data_size
            self.access_order[cache_key] = time.time()
            
            logger.info(
                f"[{Config.EDGE_ID}] Cached: {video_id} ({quality}) {start}-{end} "
                f"({data_size / 1024:.2f} KB)"
            )
        except Exception as e:
            logger.error(f"[{Config.EDGE_ID}] Cache write error: {e}")
    
    def get_stats(self):
        """Get cache statistics"""
        return {
            'edge_id': Config.EDGE_ID,
            'location': Config.EDGE_LOCATION,
            'cached_items': len(self.access_order),
            'cache_size_bytes': self.current_size,
            'cache_size_mb': self.current_size / 1024 / 1024,
            'max_size_mb': self.max_size_bytes / 1024 / 1024,
            'usage_percent': (self.current_size / self.max_size_bytes) * 100
        }

# Initialize cache
cache = LRUCache(
    Config.CACHE_DIR,
    Config.MAX_CACHE_SIZE_GB * 1024 * 1024 * 1024
)

def parse_range_header(range_header: str, file_size: int):
    """Parse HTTP Range header"""
    if not range_header:
        return 0, file_size - 1, file_size
    
    match = re.search(r'bytes=(\d+)-(\d*)', range_header)
    if not match:
        return 0, file_size - 1, file_size
    
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else file_size - 1
    
    start = max(0, min(start, file_size - 1))
    end = max(start, min(end, file_size - 1))
    
    return start, end, file_size

def fetch_from_origin(video_id: str, quality: str, range_header: str = None):
    """Fetch video from origin server"""
    # Align with streaming_service path: /api/v1/videos/<id>/stream
    url = f"{Config.ORIGIN_URL}/api/v1/videos/{video_id}/stream"
    params = {'quality': quality}
    headers = {}
    
    if range_header:
        headers['Range'] = range_header
    
    logger.info(f"[{Config.EDGE_ID}] Fetching from origin: {video_id} ({quality})")
    
    try:
        response = requests.get(url, params=params, headers=headers, stream=True, timeout=30)
        return response
    except Exception as e:
        logger.error(f"[{Config.EDGE_ID}] Origin fetch error: {e}")
        return None

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'cdn-edge',
        'edge_id': Config.EDGE_ID,
        'location': Config.EDGE_LOCATION,
        'timestamp': datetime.utcnow().isoformat()
    }), 200

@app.route('/api/v1/stream/<video_id>', methods=['GET'])
def stream_video(video_id):
    """
    Stream video from edge cache or origin
    
    Query params:
        quality: 360p|480p|720p|1080p|original (default: 720p)
    
    Headers:
        Range: bytes=start-end (optional)
    """
    quality = request.args.get('quality', '720p')
    range_header = request.headers.get('Range')
    
    logger.info(
        f"[{Config.EDGE_ID}] Stream request: {video_id} ({quality}) "
        f"Range: {range_header} Client: {request.remote_addr}"
    )
    
    # Try cache first
    if range_header:
        # Parse range
        match = re.search(r'bytes=(\d+)-(\d*)', range_header)
        if match:
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else start + Config.CHUNK_SIZE - 1
            
            # Check cache
            cached_data = cache.get(video_id, quality, start, end)
            
            if cached_data:
                # Serve from cache
                response = Response(
                    cached_data,
                    status=206,
                    mimetype='video/mp4'
                )
                
                response.headers['Content-Length'] = len(cached_data)
                response.headers['Content-Range'] = f'bytes {start}-{start + len(cached_data) - 1}/*'
                response.headers['Accept-Ranges'] = 'bytes'
                response.headers['X-Cache'] = 'HIT'
                response.headers['X-Edge-Server'] = Config.EDGE_ID
                response.headers['X-Edge-Location'] = Config.EDGE_LOCATION
                
                return response
    
    # Cache miss - fetch from origin
    origin_response = fetch_from_origin(video_id, quality, range_header)
    
    if not origin_response:
        return jsonify({'error': 'Failed to fetch from origin'}), 502
    
    if origin_response.status_code not in [200, 206]:
        return jsonify({'error': 'Origin error'}), origin_response.status_code
    
    # Stream response and cache chunks
    def generate_and_cache():
        """Stream from origin and cache chunks"""
        chunk_start = 0
        if range_header:
            match = re.search(r'bytes=(\d+)-', range_header)
            if match:
                chunk_start = int(match.group(1))
        
        current_pos = chunk_start
        buffer = b''
        
        for chunk in origin_response.iter_content(chunk_size=Config.CHUNK_SIZE):
            if chunk:
                buffer += chunk
                
                # Cache when buffer reaches chunk size
                if len(buffer) >= Config.CHUNK_SIZE:
                    cache.put(
                        video_id,
                        quality,
                        current_pos,
                        current_pos + len(buffer) - 1,
                        buffer
                    )
                    current_pos += len(buffer)
                    buffer = b''
                
                yield chunk
        
        # Cache remaining buffer
        if buffer:
            cache.put(
                video_id,
                quality,
                current_pos,
                current_pos + len(buffer) - 1,
                buffer
            )
    
    # Build response
    response = Response(
        generate_and_cache(),
        status=origin_response.status_code,
        mimetype='video/mp4',
        direct_passthrough=True
    )
    
    # Copy headers from origin
    for header in ['Content-Length', 'Content-Range', 'Accept-Ranges']:
        if header in origin_response.headers:
            response.headers[header] = origin_response.headers[header]
    
    response.headers['X-Cache'] = 'MISS'
    response.headers['X-Edge-Server'] = Config.EDGE_ID
    response.headers['X-Edge-Location'] = Config.EDGE_LOCATION
    
    return response

@app.route('/api/v1/videos/<video_id>/info', methods=['GET'])
def get_video_info(video_id):
    """Proxy video info from origin"""
    try:
        url = f"{Config.ORIGIN_URL}/api/v1/videos/{video_id}/info"
        response = requests.get(url, timeout=10)
        return (response.content, response.status_code, response.headers.items())
    except Exception as e:
        logger.error(f"[{Config.EDGE_ID}] Proxy error: {e}")
        return jsonify({'error': 'Failed to fetch from origin'}), 502

@app.route('/api/v1/cache/stats', methods=['GET'])
def get_cache_stats():
    """Get cache statistics"""
    stats = cache.get_stats()
    
    # Add Redis stats if available
    try:
        redis_info = redis_client.info('stats')
        stats['redis_hits'] = redis_info.get('keyspace_hits', 0)
        stats['redis_misses'] = redis_info.get('keyspace_misses', 0)
    except:
        pass
    
    return jsonify({
        'success': True,
        'data': stats
    }), 200

@app.route('/api/v1/cache/clear', methods=['POST'])
def clear_cache():
    """Clear edge cache"""
    try:
        cleared = 0
        for filename in os.listdir(cache.cache_dir):
            filepath = os.path.join(cache.cache_dir, filename)
            if os.path.isfile(filepath):
                os.remove(filepath)
                cleared += 1
        
        # Reset cache state
        cache.current_size = 0
        cache.access_order.clear()
        
        logger.info(f"[{Config.EDGE_ID}] Cache cleared: {cleared} files")
        
        return jsonify({
            'success': True,
            'message': f'Cleared {cleared} cached files'
        }), 200
        
    except Exception as e:
        logger.error(f"[{Config.EDGE_ID}] Clear cache error: {e}")
        return jsonify({'error': 'Failed to clear cache'}), 500

if __name__ == '__main__':
    logger.info(f"Starting CDN Edge Server: {Config.EDGE_ID} ({Config.EDGE_LOCATION})")
    logger.info(f"Origin: {Config.ORIGIN_URL}")
    logger.info(f"Cache: {Config.CACHE_DIR} (max {Config.MAX_CACHE_SIZE_GB}GB)")
    
    app.run(host='0.0.0.0', port=9000, debug=True)