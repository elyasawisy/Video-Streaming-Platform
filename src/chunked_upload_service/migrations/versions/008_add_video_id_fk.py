"""Add foreign key constraint to chunked_uploads table.

Revision ID: 008_add_video_id_fk
Revises: 007_add_status
Create Date: 2024-01-18 22:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '008_add_video_id_fk'
down_revision = '007_add_status'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the foreign key constraint
    op.create_foreign_key(
        'chunked_uploads_video_id_fkey',
        'chunked_uploads', 'videos',
        ['video_id'], ['id'],
        ondelete='CASCADE'  # Delete upload record when video is deleted
    )


def downgrade() -> None:
    op.drop_constraint('chunked_uploads_video_id_fkey', 'chunked_uploads')