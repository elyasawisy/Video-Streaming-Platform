"""add uploaded_chunks column to chunked_uploads

Revision ID: 003
Revises: 002
Create Date: 2025-11-06 23:37:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('chunked_uploads',
                  sa.Column('uploaded_chunks', sa.Integer(), 
                           nullable=False, server_default='0'))

def downgrade():
    op.drop_column('chunked_uploads', 'uploaded_chunks')