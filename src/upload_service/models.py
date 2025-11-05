"""
Database Models for Upload Service
Enhanced for production use
"""
from sqlalchemy import Column, String, Integer, DateTime, BigInteger, Enum, Boolean, Text, Index
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import enum

Base = declarative_base()

class VideoStatus(enum.Enum):
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    QUEUED = "queued"
    TRANSCODING = "transcoding"
    READY = "ready"
    FAILED = "failed"
    DELETED = "deleted"

class Video(Base):
    __tablename__ = 'videos'
    
    id = Column(String(36), primary_key=True)
    title = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    file_hash = Column(String(64), nullable=True)
    mime_type = Column(String(100), nullable=False)
    status = Column(Enum(VideoStatus), default=VideoStatus.UPLOADING, index=True)
    upload_method = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    uploaded_at = Column(DateTime, nullable=True)
    transcoded_at = Column(DateTime, nullable=True)
    uploader_id = Column(String(36), nullable=True, index=True)
    duration = Column(Integer, nullable=True)
    
    # Enhanced fields for production
    description = Column(Text, nullable=True)
    thumbnail_path = Column(String(500), nullable=True)
    is_public = Column(Boolean, default=True)
    view_count = Column(Integer, default=0)
    like_count = Column(Integer, default=0)
    tags = Column(Text, nullable=True)  # JSON string of tags
    category = Column(String(100), nullable=True, index=True)
    quality_available = Column(Text, nullable=True)  # JSON string of available qualities
    deleted_at = Column(DateTime, nullable=True)
    
    # Indexes for common queries
    __table_args__ = (
        Index('idx_status_created', 'status', 'created_at'),
        Index('idx_uploader_status', 'uploader_id', 'status'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'filename': self.filename,
            'original_filename': self.original_filename,
            'file_size': self.file_size,
            'file_hash': self.file_hash,
            'mime_type': self.mime_type,
            'status': self.status.value if isinstance(self.status, VideoStatus) else self.status,
            'upload_method': self.upload_method,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'transcoded_at': self.transcoded_at.isoformat() if self.transcoded_at else None,
            'uploader_id': self.uploader_id,
            'duration': self.duration,
            'description': self.description,
            'thumbnail_path': self.thumbnail_path,
            'is_public': self.is_public,
            'view_count': self.view_count,
            'like_count': self.like_count,
            'tags': self.tags,
            'category': self.category,
            'quality_available': self.quality_available,
        }

class UploadMetrics(Base):
    __tablename__ = 'upload_metrics'
    
    id = Column(String(36), primary_key=True)
    video_id = Column(String(36), nullable=False, index=True)
    upload_method = Column(String(50), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    upload_duration = Column(Integer, nullable=False)
    throughput = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

