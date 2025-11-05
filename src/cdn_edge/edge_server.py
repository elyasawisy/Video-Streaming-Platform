"""
CDN Edge Server
Caches video content from origin server
"""
import os
import re
import time
import hashlib
import logging
from datetime import datetime
from flask import Flask, request, Response, jsonify
import requests
import redis
from collections import OrderedDict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
class Config:
    # TODO: set EDGE_ID per deployment (e.g., via environment)
    EDGE_ID = os.getenv('EDGE_ID', 'edge-1')
    EDGE_LOCATION = os.getenv('EDGE_LOCATION', 'US-East')
    # TODO: set ORIGIN_URL to the streaming service base URL
    ORIGIN_URL = os.getenv('ORIGIN_URL', 'http://streaming_service:8003')
    REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379')
    CACHE_DIR = os.getenv('CACHE_DIR', './cache')
    # TODO: tune cache size based on node storage capacity
    MAX_CACHE_SIZE_GB = int(os.getenv('MAX_CACHE_SIZE_GB', 10))
    CHUNK_SIZE = 1024 * 1024  # 1MB
    CACHE_TTL = 3600  # 1 hour

# Redis client for metadata
redis_client = redis.from_url(Config.REDIS_URL)

# Flask app
app = Flask(__name__)

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