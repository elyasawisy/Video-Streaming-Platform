"""Add status column to chunked_uploads table.

Revision ID: 007_add_status
Revises: 006_add_chunk_size
Create Date: 2024-01-18 22:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007_add_status'
down_revision = '006_add_chunk_size'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the enum type first
    op.execute("""
        CREATE TYPE upload_status AS ENUM ('pending', 'uploading', 'completed', 'failed', 'expired')
    """)

    # Add the status column with a default value of 'pending'
    op.add_column('chunked_uploads', sa.Column('status', sa.Enum('pending', 'uploading', 'completed', 'failed', 'expired', name='upload_status'), nullable=False, server_default='pending'))


def downgrade() -> None:
    op.drop_column('chunked_uploads', 'status')
    op.execute('DROP TYPE upload_status')