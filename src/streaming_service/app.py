"""
Streaming Service for Video Playback
Optimized for high concurrency (50k+ concurrent viewers)
Features:
- HTTP Range requests support
- Multiple quality streaming
- Redis caching for metadata
- Efficient chunk serving
"""
import os
import re
from flask import Flask, request, Response, send_file, jsonify
from flask_cors import CORS
from datetime import datetime
import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from streaming_service.config import Config
from streaming_service.models import Video, VideoStatus

# Flask App
app = Flask(__name__)
CORS(app, origins=Config.ALLOWED_ORIGINS)

# Redis for caching
redis_client = redis.from_url(Config.REDIS_URL, decode_responses=True)

# Database setup
engine = create_engine(Config.DATABASE_URL, pool_pre_ping=True, pool_size=20, max_overflow=40)
SessionLocal = sessionmaker(bind=engine)

def get_db_session():
    """Get database session"""
    return SessionLocal()

def get_video_from_cache(video_id):
    """Get video metadata from cache"""
    cache_key = f"video:{video_id}"
    cached = redis_client.get(cache_key)
    if cached:
        import json
        return json.loads(cached)
    return None

def cache_video(video_id, video_data, ttl=Config.CACHE_TTL):
    """Cache video metadata"""
    cache_key = f"video:{video_id}"
    import json
    redis_client.setex(cache_key, ttl, json.dumps(video_data))

def parse_range_header(range_header, file_size):
    """Parse HTTP Range header"""
    if not range_header:
        return None, None
    
    match = re.search(r'bytes=(\d+)-(\d*)', range_header)
    if not match:
        return None, None
    
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else file_size - 1
    
    # Validate range
    if start < 0 or start >= file_size:
        return None, None
    if end >= file_size:
        end = file_size - 1
    if end < start:
        return None, None
    
    # Limit range size
    if (end - start + 1) > Config.MAX_RANGE_SIZE:
        end = start + Config.MAX_RANGE_SIZE - 1
    
    return start, end

def get_video_path(video_id, quality='original'):
    """Get path to video file"""
    if quality == 'original':
        # Try to get from database
        db = get_db_session()
        try:
            video = db.query(Video).filter(Video.id == video_id).first()
            if video:
                filepath = os.path.join(Config.RAW_DIR, video.filename)
                if os.path.exists(filepath):
                    return filepath
        finally:
            db.close()
        return None
    else:
        # Transcoded quality
        filepath = os.path.join(Config.TRANSCODED_DIR, quality, f"{video_id}.mp4")
        if os.path.exists(filepath):
            return filepath
        return None

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'streaming',
        'timestamp': datetime.utcnow().isoformat()
    }), 200

@app.route('/api/v1/videos/<video_id>/stream', methods=['GET'])
def stream_video(video_id):
    """
    Stream video with HTTP Range support
    Supports multiple qualities and efficient chunk serving
    """
    quality = request.args.get('quality', 'original')
    
    # Get video path
    filepath = get_video_path(video_id, quality)
    if not filepath or not os.path.exists(filepath):
        return jsonify({'error': 'Video not found'}), 404
    
    file_size = os.path.getsize(filepath)
    
    # Parse Range header
    range_header = request.headers.get('Range')
    start, end = parse_range_header(range_header, file_size)
    
    # Determine content length
    if start is not None and end is not None:
        content_length = end - start + 1
    else:
        start = 0
        end = file_size - 1
        content_length = file_size
    
    # Generate response
    def generate():
        with open(filepath, 'rb') as f:
            f.seek(start)
            remaining = content_length
            chunk_size = Config.CHUNK_SIZE
            
            while remaining > 0:
                read_size = min(chunk_size, remaining)
                chunk = f.read(read_size)
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
    
    response = Response(
        generate(),
        status=206 if range_header else 200,
        mimetype='video/mp4',
        headers={
            'Content-Length': str(content_length),
            'Accept-Ranges': 'bytes',
            'Content-Range': f'bytes {start}-{end}/{file_size}' if range_header else None,
            'Cache-Control': 'public, max-age=3600',
            'Content-Type': 'video/mp4',
        }
    )
    
    return response

@app.route('/api/v1/videos/<video_id>/info', methods=['GET'])
def get_video_info(video_id):
    """Get video information and available qualities"""
    # Check cache first
    cached = get_video_from_cache(video_id)
    if cached:
        return jsonify(cached), 200
    
    # Get from database
    db = get_db_session()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return jsonify({'error': 'Video not found'}), 404
        
        # Check available qualities
        available_qualities = ['original']
        if video.quality_available:
            import json
            try:
                qualities = json.loads(video.quality_available)
                available_qualities.extend(qualities)
            except:
                pass
        
        # Check which qualities actually exist
        existing_qualities = []
        for quality in available_qualities:
            if get_video_path(video_id, quality):
                existing_qualities.append(quality)
        
        response_data = {
            'video_id': video.id,
            'title': video.title,
            'duration': video.duration,
            'file_size': video.file_size,
            'status': video.status.value if isinstance(video.status, VideoStatus) else video.status,
            'available_qualities': existing_qualities,
            'thumbnail_path': video.thumbnail_path,
            'created_at': video.created_at.isoformat() if video.created_at else None,
        }
        
        # Cache the response
        cache_video(video_id, response_data)
        
        return jsonify(response_data), 200
        
    finally:
        db.close()

@app.route('/api/v1/videos/<video_id>/chunk', methods=['GET'])
def get_video_chunk(video_id):
    """
    Get specific chunk of video
    Optimized for CDN/edge serving
    """
    quality = request.args.get('quality', 'original')
    chunk = request.args.get('chunk', 0, type=int)
    chunk_size = request.args.get('chunk_size', Config.CHUNK_SIZE, type=int)
    
    filepath = get_video_path(video_id, quality)
    if not filepath or not os.path.exists(filepath):
        return jsonify({'error': 'Video not found'}), 404
    
    file_size = os.path.getsize(filepath)
    start = chunk * chunk_size
    end = min(start + chunk_size - 1, file_size - 1)
    
    if start >= file_size:
        return jsonify({'error': 'Chunk out of range'}), 400
    
    def generate():
        with open(filepath, 'rb') as f:
            f.seek(start)
            remaining = end - start + 1
            read_chunk_size = min(1024 * 64, remaining)  # 64KB reads
            
            while remaining > 0:
                read_size = min(read_chunk_size, remaining)
                data = f.read(read_size)
                if not data:
                    break
                remaining -= len(data)
                yield data
    
    response = Response(
        generate(),
        status=200,
        mimetype='video/mp4',
        headers={
            'Content-Length': str(end - start + 1),
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'public, max-age=86400',
            'Content-Type': 'video/mp4',
        }
    )
    
    return response

@app.route('/api/v1/videos/<video_id>/manifest', methods=['GET'])
def get_manifest(video_id):
    """
    Get HLS/DASH manifest for adaptive streaming
    Returns M3U8 playlist for HLS
    """
    db = get_db_session()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return jsonify({'error': 'Video not found'}), 404
        
        # Get available qualities
        available_qualities = []
        for quality in ['360p', '480p', '720p', '1080p']:
            if get_video_path(video_id, quality):
                available_qualities.append(quality)
        
        if not available_qualities:
            return jsonify({'error': 'No transcoded qualities available'}), 404
        
        # Generate M3U8 playlist
        base_url = request.url_root.rstrip('/')
        manifest = "#EXTM3U\n"
        manifest += "#EXT-X-VERSION:3\n"
        
        for quality in available_qualities:
            filepath = get_video_path(video_id, quality)
            if filepath:
                file_size = os.path.getsize(filepath)
                # Estimate bitrate (rough calculation)
                bitrate = int((file_size * 8) / (video.duration or 60)) if video.duration else 2000000
                
                manifest += f"#EXT-X-STREAM-INF:BANDWIDTH={bitrate},RESOLUTION={_get_resolution(quality)}\n"
                manifest += f"{base_url}/api/v1/videos/{video_id}/stream?quality={quality}\n"
        
        manifest += "#EXT-X-ENDLIST\n"
        
        response = Response(
            manifest,
            mimetype='application/vnd.apple.mpegurl',
            headers={
                'Cache-Control': 'public, max-age=3600',
            }
        )
        
        return response
        
    finally:
        db.close()

def _get_resolution(quality):
    """Get resolution string for quality"""
    resolutions = {
        '360p': '640x360',
        '480p': '854x480',
        '720p': '1280x720',
        '1080p': '1920x1080'
    }
    return resolutions.get(quality, '1280x720')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8003, threaded=True, debug=False)

