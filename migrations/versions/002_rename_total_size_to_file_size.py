"""rename total_size to file_size in chunked_uploads

Revision ID: 002
Revises: 001
Create Date: 2025-11-06 23:30:00.000000

"""
from alembic import op

# revision identifiers
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None

def upgrade():
    op.alter_column('chunked_uploads', 'total_size',
                    new_column_name='file_size',
                    existing_type=None,
                    nullable=False)

def downgrade():
    op.alter_column('chunked_uploads', 'file_size',
                    new_column_name='total_size',
                    existing_type=None,
                    nullable=False)