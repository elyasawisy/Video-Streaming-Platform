"""
Routes for Upload Service
Separated from app.py for better organization
"""
import os
import uuid
import hashlib
import time
import json
from datetime import datetime
from flask import request, jsonify
from werkzeug.utils import secure_filename
from sqlalchemy import or_, func

from upload_service.models import Video, VideoStatus, UploadMetrics


def init_routes(app, db, publish_transcode_job, calculate_file_hash):
    """Initialize routes with app context"""
    
    def allowed_file(filename):
        """Check if file extension is allowed"""
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


    @app.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        return jsonify({
            'status': 'healthy',
            'service': 'http2-upload',
            'timestamp': datetime.utcnow().isoformat()
        }), 200


    @app.route('/api/v1/upload', methods=['POST'])
    def upload_video():
        """
        HTTP/2 Streaming Upload Endpoint
        Accepts large video files in a single streaming request
        """
        start_time = time.time()
    
        # Validate request
        if 'video' not in request.files:
            return jsonify({'error': 'No video file provided'}), 400
    
        video_file = request.files['video']
        if video_file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400
    
        if not allowed_file(video_file.filename):
            return jsonify({
                'error': 'Invalid file type',
                'allowed_types': list(app.config['ALLOWED_EXTENSIONS'])
            }), 400
    
        # Get metadata from form
        title = request.form.get('title', 'Untitled Video')
        uploader_id = request.form.get('uploader_id', 'anonymous')
        description = request.form.get('description', '')
        category = request.form.get('category', None)
        tags = request.form.get('tags', None)
    
        # Generate unique identifiers
        video_id = str(uuid.uuid4())
        original_filename = secure_filename(video_file.filename)
        file_extension = original_filename.rsplit('.', 1)[1].lower()
        filename = f"{video_id}.{file_extension}"
        filepath = os.path.join(app.config['UPLOAD_DIR'], filename)
    
        try:
        # Create video record
            video = Video(
            id=video_id,
            title=title,
            filename=filename,
            original_filename=original_filename,
            file_size=0,
            mime_type=video_file.content_type or 'video/mp4',
            status=VideoStatus.UPLOADING,
            upload_method='http2',
            uploader_id=uploader_id,
            description=description,
            category=category,
            tags=tags
        )
            db.session.add(video)
            db.session.commit()
        
        # Save file with streaming to handle large files
            app.logger.info(f"Starting upload for video {video_id}: {original_filename}")
            video_file.save(filepath)
        
        # Get file size and calculate hash
            file_size = os.path.getsize(filepath)
            file_hash = calculate_file_hash(filepath)
        
        # Update video record
            video.file_size = file_size
            video.file_hash = file_hash
            video.status = VideoStatus.UPLOADED
            video.uploaded_at = datetime.utcnow()
            db.session.commit()
        
        # Calculate metrics
            upload_duration = int((time.time() - start_time) * 1000)
            throughput = int(file_size / (time.time() - start_time)) if (time.time() - start_time) > 0 else 0
        
        # Store metrics
            metrics = UploadMetrics(
            id=str(uuid.uuid4()),
            video_id=video_id,
            upload_method='http2',
            file_size=file_size,
            upload_duration=upload_duration,
            throughput=throughput
        )
            db.session.add(metrics)
            db.session.commit()
        
        # Publish to transcode queue
            job_data = {
            'video_id': video_id,
            'filename': filename,
            'filepath': filepath,
            'original_filename': original_filename,
            'file_size': file_size,
            'upload_method': 'http2'
        }
        
            if publish_transcode_job(job_data):
                video.status = VideoStatus.QUEUED
                db.session.commit()
        
            response_data = video.to_dict()
            response_data['upload_duration_ms'] = upload_duration
            response_data['throughput_bps'] = throughput
        
            app.logger.info(f"Upload completed for video {video_id} in {upload_duration}ms")
            return jsonify({
                'success': True,
                'message': 'Video uploaded successfully',
                'data': response_data
            }), 201
        
        except Exception as e:
            app.logger.error(f"Upload failed: {str(e)}")
        
        # Cleanup on failure
            if os.path.exists(filepath):
                os.remove(filepath)
        
            try:
                db.session.rollback()
            except:
                pass
        
            return jsonify({
                'success': False,
                'error': 'Upload failed',
                'details': str(e)
            }), 500


    @app.route('/api/v1/videos/<video_id>', methods=['GET'])
    def get_video_status(video_id):
        """Get video upload and processing status"""
        try:
            video = db.session.query(Video).filter(Video.id == video_id).first()
            
            if not video:
                return jsonify({'error': 'Video not found'}), 404
            
            data = video.to_dict()
            
            return jsonify({
                'success': True,
                'data': data
            }), 200
            
        except Exception as e:
            app.logger.error(f"Error fetching video: {str(e)}")
            return jsonify({'error': 'Internal server error'}), 500


    @app.route('/api/v1/videos', methods=['GET'])
    def list_videos():
        """List all videos with pagination and filtering"""
        try:
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            status = request.args.get('status', None)
            uploader_id = request.args.get('uploader_id', None)
            category = request.args.get('category', None)
            search = request.args.get('search', None)
            
            query = db.session.query(Video)
            
            # Filters
            if status:
                try:
                    status_enum = VideoStatus[status.upper()]
                    query = query.filter(Video.status == status_enum)
                except (KeyError, AttributeError):
                    pass
            
            if uploader_id:
                query = query.filter(Video.uploader_id == uploader_id)
            
            if category:
                query = query.filter(Video.category == category)
            
            if search:
                search_term = f"%{search}%"
                query = query.filter(
                    or_(
                        Video.title.ilike(search_term),
                        Video.description.ilike(search_term)
                    )
                )
            
            # Exclude deleted videos
            query = query.filter(Video.status != VideoStatus.DELETED)
            
            # Pagination
            total = query.count()
            videos = query.order_by(Video.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
            
            data = [video.to_dict() for video in videos]
            
            return jsonify({
                'success': True,
                'count': len(data),
                'total': total,
                'page': page,
                'per_page': per_page,
                'data': data
            }), 200
            
        except Exception as e:
            app.logger.error(f"Error listing videos: {str(e)}")
            return jsonify({'error': 'Internal server error'}), 500


    @app.route('/api/v1/videos/<video_id>', methods=['PUT'])
    def update_video(video_id):
        """Update video metadata"""
        try:
            video = db.session.query(Video).filter(Video.id == video_id).first()
            
            if not video:
                return jsonify({'error': 'Video not found'}), 404
            
            data = request.get_json()
            
            # Update allowed fields
            if 'title' in data:
                video.title = data['title']
            if 'description' in data:
                video.description = data['description']
            if 'category' in data:
                video.category = data['category']
            if 'tags' in data:
                video.tags = json.dumps(data['tags']) if isinstance(data['tags'], list) else data['tags']
            if 'is_public' in data:
                video.is_public = data['is_public']
            
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Video updated successfully',
                'data': video.to_dict()
            }), 200
            
        except Exception as e:
            app.logger.error(f"Error updating video: {str(e)}")
            db.session.rollback()
            return jsonify({'error': 'Internal server error'}), 500


    @app.route('/api/v1/videos/<video_id>', methods=['DELETE'])
    def delete_video(video_id):
        """Soft delete a video"""
        try:
            video = db.session.query(Video).filter(Video.id == video_id).first()
            
            if not video:
                return jsonify({'error': 'Video not found'}), 404
            
            # Soft delete
            video.status = VideoStatus.DELETED
            video.deleted_at = datetime.utcnow()
            
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Video deleted successfully'
            }), 200
            
        except Exception as e:
            app.logger.error(f"Error deleting video: {str(e)}")
            db.session.rollback()
            return jsonify({'error': 'Internal server error'}), 500


    @app.route('/api/v1/videos/search', methods=['GET'])
    def search_videos():
        """Search videos by title or description"""
        try:
            query_term = request.args.get('q', '')
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            
            if not query_term:
                return jsonify({'error': 'Search query required'}), 400
            
            search_term = f"%{query_term}%"
            query = db.session.query(Video).filter(
                or_(
                    Video.title.ilike(search_term),
                    Video.description.ilike(search_term)
                )
            ).filter(Video.status != VideoStatus.DELETED)
            
            total = query.count()
            videos = query.order_by(Video.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
            
            data = [video.to_dict() for video in videos]
            
            return jsonify({
                'success': True,
                'count': len(data),
                'total': total,
                'page': page,
                'per_page': per_page,
                'query': query_term,
                'data': data
            }), 200
            
        except Exception as e:
            app.logger.error(f"Error searching videos: {str(e)}")
            return jsonify({'error': 'Internal server error'}), 500


    @app.route('/api/v1/metrics', methods=['GET'])
    def get_metrics():
        """Get upload metrics for analysis"""
        try:
            metrics = db.session.query(UploadMetrics).filter(
                UploadMetrics.upload_method == 'http2'
            ).order_by(UploadMetrics.created_at.desc()).limit(100).all()
            
            data = [{
                'video_id': m.video_id,
                'file_size': m.file_size,
                'upload_duration_ms': m.upload_duration,
                'throughput_bps': m.throughput,
                'created_at': m.created_at.isoformat()
            } for m in metrics]
            
            # Calculate averages
            if data:
                avg_duration = sum(m['upload_duration_ms'] for m in data) / len(data)
                avg_throughput = sum(m['throughput_bps'] for m in data) / len(data)
            else:
                avg_duration = 0
                avg_throughput = 0
            
            return jsonify({
                'success': True,
                'count': len(data),
                'averages': {
                    'upload_duration_ms': avg_duration,
                    'throughput_bps': avg_throughput
                },
                'data': data
            }), 200
            
        except Exception as e:
            app.logger.error(f"Error fetching metrics: {str(e)}")
            return jsonify({'error': 'Internal server error'}), 500


    @app.errorhandler(413)
    def request_entity_too_large(error):
        """Handle file too large error"""
        return jsonify({
            'error': 'File too large',
            'max_size_bytes': app.config['MAX_CONTENT_LENGTH']
        }), 413

