"""
HTTP/2 Streaming Upload Service
Handles large video file uploads using HTTP/2 multiplexing
"""
import os
import sys
import hashlib
from flask import Flask
import pika
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

from config import Config
from models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

# Flask App
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = Config.MAX_UPLOAD_SIZE
app.config['ALLOWED_EXTENSIONS'] = Config.ALLOWED_EXTENSIONS
app.config['UPLOAD_DIR'] = Config.UPLOAD_DIR

# Ensure upload directory exists
os.makedirs(Config.UPLOAD_DIR, exist_ok=True)

# Database initialization
engine = create_engine(Config.DATABASE_URL, pool_pre_ping=True)
Base.metadata.create_all(engine)
session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)

# Add session to app context
app.Session = Session

@app.before_request
def before_request():
    """Create session for each request"""
    if not hasattr(app, 'db'):
        app.db = Session()

@app.teardown_appcontext
def shutdown_session(exception=None):
    """Remove session at end of request"""
    if hasattr(app, 'db'):
        Session.remove()

# Helper functions
def get_rabbitmq_connection():
    """Create RabbitMQ connection and channel"""
    try:
        params = pika.URLParameters(Config.RABBITMQ_URL)
        connection = pika.BlockingConnection(params)
        channel = connection.channel()
        channel.queue_declare(queue=Config.RABBITMQ_QUEUE, durable=True)
        return connection, channel
    except Exception as e:
        app.logger.error(f"RabbitMQ connection failed: {e}")
        return None, None

def publish_transcode_job(video_data):
    """Publish transcode job to RabbitMQ"""
    try:
        connection, channel = get_rabbitmq_connection()
        if not channel:
            return False
        
        message = json.dumps(video_data)
        channel.basic_publish(
            exchange='',
            routing_key=Config.RABBITMQ_QUEUE,
            body=message,
            properties=pika.BasicProperties(
                delivery_mode=2,  # Make message persistent
                content_type='application/json'
            )
        )
        connection.close()
        app.logger.info(f"Published transcode job for video {video_data['video_id']}")
        return True
    except Exception as e:
        app.logger.error(f"Failed to publish job: {e}")
        return False

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

def calculate_file_hash(filepath):
    """Calculate SHA256 hash of file"""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

# Import and initialize routes after app is created
from routes import init_routes
init_routes(app, Session, publish_transcode_job, calculate_file_hash)

if __name__ == '__main__':
    # For development with HTTP/2, use Hypercorn:
    # hypercorn app:app --bind 0.0.0.0:8001
    app.run(host='0.0.0.0', port=8001, debug=True)
