"""add cases table and structured report fields

Revision ID: 0002_cases_and_report_fields
Revises: 0001_create_reports_table
Create Date: 2026-10-15 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_cases_and_report_fields"
down_revision = "0001_create_reports_table"
branch_labels = None
depends_on = None

REPORT_FIELDS = (
    "patient",
    "specimen",
    "gross_description",
    "microscopic_description",
    "diagnosis",
    "comments",
)


def upgrade():
    op.create_table(
        "cases",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("case_number", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("case_number", name="uq_cases_case_number"),
    )

    op.add_column("reports", sa.Column("case_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_reports_case_id", "reports", "cases", ["case_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_reports_case_id", "reports", ["case_id"])

    op.add_column("reports", sa.Column("session_id", sa.String(length=128), nullable=True))
    op.create_unique_constraint("uq_reports_session_id", "reports", ["session_id"])

    for name in REPORT_FIELDS:
        op.add_column("reports", sa.Column(name, sa.Text(), nullable=False, server_default=""))
    op.add_column("reports", sa.Column("comment_source", sa.String(length=10), nullable=True))
    op.create_check_constraint(
        "ck_reports_comment_source",
        "reports",
        "comment_source IS NULL OR comment_source IN ('doctor', 'ai')",
    )

    op.execute("UPDATE reports SET status = 'draft' WHERE status IS NULL")
    op.alter_column(
        "reports",
        "status",
        existing_type=sa.String(length=50),
        nullable=False,
        server_default="draft",
    )
    op.create_check_constraint("ck_reports_status", "reports", "status IN ('draft', 'approved')")

    op.add_column("reports", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("reports", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("reports", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))

    # The free-text `content` column is superseded by the six report fields.
    op.drop_column("reports", "content")


def downgrade():
    op.add_column("reports", sa.Column("content", sa.Text(), nullable=True))
    op.drop_column("reports", "approved_at")
    op.drop_column("reports", "updated_at")
    op.drop_column("reports", "created_at")
    op.drop_constraint("ck_reports_status", "reports", type_="check")
    op.alter_column(
        "reports",
        "status",
        existing_type=sa.String(length=50),
        nullable=True,
        server_default="draft",
    )
    op.drop_constraint("ck_reports_comment_source", "reports", type_="check")
    op.drop_column("reports", "comment_source")
    for name in reversed(REPORT_FIELDS):
        op.drop_column("reports", name)
    op.drop_constraint("uq_reports_session_id", "reports", type_="unique")
    op.drop_column("reports", "session_id")
    op.drop_index("ix_reports_case_id", table_name="reports")
    op.drop_constraint("fk_reports_case_id", "reports", type_="foreignkey")
    op.drop_column("reports", "case_id")
    op.drop_table("cases")
