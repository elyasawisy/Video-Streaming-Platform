"""create initial tables

Revision ID: 001
Create Date: 2025-11-06 20:20:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers
revision = '001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Enable required extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "hstore"')
    
    # Create videos table
    op.create_table(
        'videos',
        sa.Column('id', UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('original_filename', sa.String(length=255)),
        sa.Column('file_size', sa.BigInteger(), nullable=False, default=0),
        sa.Column('file_hash', sa.String(length=64)),
        sa.Column('mime_type', sa.String(length=100)),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('upload_method', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('uploaded_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('transcoded_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('uploader_id', sa.String(length=255)),
        sa.Column('duration', sa.Integer),
        sa.Column('description', sa.Text),
        sa.Column('thumbnail_path', sa.String(length=255)),
        sa.Column('is_public', sa.Boolean, server_default='true'),
        sa.Column('view_count', sa.Integer, server_default='0'),
        sa.Column('like_count', sa.Integer, server_default='0'),
        sa.Column('tags', JSONB),
        sa.Column('category', sa.String(length=100)),
        sa.Column('quality_available', JSONB),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create upload_metrics table
    op.create_table(
        'upload_metrics',
        sa.Column('id', UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('video_id', UUID(), nullable=True),
        sa.Column('upload_method', sa.String(length=50), nullable=False),
        sa.Column('file_size', sa.BigInteger(), nullable=False),
        sa.Column('upload_duration', sa.Integer(), nullable=False),
        sa.Column('throughput', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['video_id'], ['videos.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create chunked_uploads table
    op.create_table(
        'chunked_uploads',
        sa.Column('id', UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('video_id', UUID(), nullable=True),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('total_chunks', sa.Integer(), nullable=False),
        sa.Column('chunk_size', sa.Integer(), nullable=False),
        sa.Column('total_size', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['video_id'], ['videos.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index('idx_videos_status', 'videos', ['status'])
    op.create_index('idx_videos_uploader', 'videos', ['uploader_id'])
    op.create_index('idx_videos_created_at', 'videos', ['created_at'])
    op.create_index('idx_upload_metrics_method', 'upload_metrics', ['upload_method'])
    op.create_index('idx_chunked_uploads_video_id', 'chunked_uploads', ['video_id'])

def downgrade():
    op.drop_index('idx_chunked_uploads_video_id')
    op.drop_index('idx_upload_metrics_method')
    op.drop_index('idx_videos_created_at')
    op.drop_index('idx_videos_uploader')
    op.drop_index('idx_videos_status')
    op.drop_table('chunked_uploads')
    op.drop_table('upload_metrics')
    op.drop_table('videos')