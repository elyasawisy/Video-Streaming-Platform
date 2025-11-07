"""Add retry_count column to upload_metrics table.

Revision ID: 009_add_retry_count
Revises: 008_add_video_id_fk
Create Date: 2024-01-18 22:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '009_add_retry_count'
down_revision = '008_add_video_id_fk'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('upload_metrics', sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('upload_metrics', 'retry_count')
