"""add is_complete column to chunked_uploads

Revision ID: 004
Revises: 003
Create Date: 2025-11-06 23:40:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('chunked_uploads',
                  sa.Column('is_complete', sa.Boolean(), 
                           nullable=False, server_default='false'))

def downgrade():
    op.drop_column('chunked_uploads', 'is_complete')