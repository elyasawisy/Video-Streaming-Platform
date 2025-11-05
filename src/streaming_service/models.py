"""
Database Models for Streaming Service
"""
import sys
import os

# Import from upload_service models
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from upload_service.models import Video, VideoStatus

__all__ = ['Video', 'VideoStatus']

