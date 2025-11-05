"""
Video Transcoder using FFmpeg
Handles video transcoding to multiple qualities
"""
import os
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class VideoTranscoder:
    """Transcode videos using FFmpeg"""
    
    def __init__(self, config):
        self.config = config
        self.ensure_directories()
    
    def ensure_directories(self):
        """Ensure transcoded directories exist"""
        os.makedirs(self.config.TRANSCODED_DIR, exist_ok=True)
        for quality in self.config.QUALITIES:
            os.makedirs(os.path.join(self.config.TRANSCODED_DIR, quality), exist_ok=True)
    
    def get_video_info(self, filepath):
        """Get video metadata using ffprobe"""
        try:
            cmd = [
                'ffprobe', '-v', 'error', '-show_entries',
                'format=duration,size,bit_rate', '-show_entries',
                'stream=width,height,codec_name', '-of', 'json',
                filepath
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            import json
            info = json.loads(result.stdout)
            
            duration = float(info['format'].get('duration', 0))
            width = height = 0
            if 'streams' in info and len(info['streams']) > 0:
                width = int(info['streams'][0].get('width', 0))
                height = int(info['streams'][0].get('height', 0))
            
            return {
                'duration': int(duration),
                'width': width,
                'height': height,
                'file_size': int(info['format'].get('size', 0))
            }
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            return None
    
    def transcode(self, video_id, input_path, quality, output_dir=None):
        """
        Transcode video to specified quality
        
        Args:
            video_id: Video ID
            input_path: Path to input video file
            quality: Target quality (360p, 480p, 720p, 1080p)
            output_dir: Output directory (defaults to transcoded_dir/quality/)
        
        Returns:
            Path to transcoded file or None on error
        """
        if not os.path.exists(input_path):
            logger.error(f"Input file not found: {input_path}")
            return None
        
        if output_dir is None:
            output_dir = os.path.join(self.config.TRANSCODED_DIR, quality)
        
        os.makedirs(output_dir, exist_ok=True)
        
        output_path = os.path.join(output_dir, f"{video_id}.mp4")
        
        # Resolution mapping
        resolution_map = {
            '360p': '640:360',
            '480p': '854:480',
            '720p': '1280:720',
            '1080p': '1920:1080'
        }
        
        resolution = resolution_map.get(quality, '1280:720')
        
        # FFmpeg command for transcoding
        cmd = [
            'ffmpeg', '-i', input_path,
            '-vf', f'scale={resolution}',
            '-c:v', 'libx264',
            '-preset', self.config.FFMPEG_PRESET,
            '-crf', str(self.config.FFMPEG_CRF),
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',
            '-y',  # Overwrite output file
            output_path
        ]
        
        try:
            logger.info(f"Transcoding {video_id} to {quality}...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour max
            )
            
            if result.returncode == 0 and os.path.exists(output_path):
                logger.info(f"Transcoding complete: {output_path}")
                return output_path
            else:
                logger.error(f"FFmpeg error: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.error(f"Transcoding timeout for {video_id} {quality}")
            return None
        except Exception as e:
            logger.error(f"Transcoding error: {e}")
            return None
    
    def transcode_all_qualities(self, video_id, input_path, progress_callback=None):
        """
        Transcode video to all configured qualities
        
        Args:
            video_id: Video ID
            input_path: Path to input video file
            progress_callback: Optional callback function(quality, progress_percent)
        
        Returns:
            Dictionary mapping quality -> output_path
        """
        results = {}
        total_qualities = len(self.config.QUALITIES)
        
        for idx, quality in enumerate(self.config.QUALITIES):
            if progress_callback:
                progress_callback(quality, int((idx / total_qualities) * 100))
            
            output_path = self.transcode(video_id, input_path, quality)
            if output_path:
                results[quality] = output_path
            else:
                logger.error(f"Failed to transcode {video_id} to {quality}")
        
        if progress_callback:
            progress_callback('complete', 100)
        
        return results

