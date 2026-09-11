"""create reports table

Revision ID: 0001_create_reports_table
Revises: 
Create Date: 2026-09-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_create_reports_table'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'reports',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True, server_default='draft'),
        schema='public',
    )


def downgrade():
    op.drop_table('reports', schema='public')
