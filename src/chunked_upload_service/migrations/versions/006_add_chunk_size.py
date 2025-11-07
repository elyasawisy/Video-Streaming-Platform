"""Add chunk_size column to chunked_uploads table.

Revision ID: 006_add_chunk_size
Revises: 005_add_expires_at
Create Date: 2024-01-18 22:11:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006_add_chunk_size'
down_revision = '005_add_expires_at'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the chunk_size column with a default value of 1MB 
    # This matches the default CHUNK_SIZE in the app config
    op.add_column('chunked_uploads', sa.Column('chunk_size', sa.Integer(), nullable=False, server_default='1048576'))


def downgrade() -> None:
    op.drop_column('chunked_uploads', 'chunk_size')