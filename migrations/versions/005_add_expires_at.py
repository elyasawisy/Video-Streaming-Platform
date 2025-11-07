"""add expires_at column to chunked_uploads

Revision ID: 005
Revises: 004
Create Date: 2025-11-06 23:53:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('chunked_uploads',
                  sa.Column('expires_at', sa.TIMESTAMP(timezone=True), nullable=True))

def downgrade():
    op.drop_column('chunked_uploads', 'expires_at')