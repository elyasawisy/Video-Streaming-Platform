"""add status column to chunked_uploads

Revision ID: 006
Revises: 005
Create Date: 2023-11-06 23:54:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None

def upgrade():
    # Create an enum type for upload status
    op.execute("CREATE TYPE upload_status AS ENUM ('pending', 'uploading', 'completed', 'failed')")
    
    # Add the status column with a default value of 'pending'
    op.add_column('chunked_uploads',
                  sa.Column('status', 
                           sa.Enum('pending', 'uploading', 'completed', 'failed', 
                                 name='upload_status'),
                           nullable=False, 
                           server_default='pending'))

def downgrade():
    # Drop the status column first
    op.drop_column('chunked_uploads', 'status')
    # Then drop the enum type
    op.execute('DROP TYPE upload_status')