"""store the dictation transcript with the approved report

Revision ID: 0004_report_transcript
Revises: 0003_users_and_case_ownership
Create Date: 2026-10-16 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0004_report_transcript"
down_revision = "0003_users_and_case_ownership"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("reports", sa.Column("transcript", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("reports", "transcript")
