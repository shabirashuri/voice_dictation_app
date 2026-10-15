"""add users; cases belong to a doctor; one report per case

Revision ID: 0003_users_and_case_ownership
Revises: 0002_cases_and_report_fields
Create Date: 2026-10-15 00:00:00.000000
"""
from alembic import context, op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0003_users_and_case_ownership"
down_revision = "0002_cases_and_report_fields"
branch_labels = None
depends_on = None


def _require_empty(*tables):
    """Existing cases/reports have no owner to assign; refuse rather than guess."""
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    for table in tables:
        count = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar()
        if count:
            raise RuntimeError(
                f"{table} has {count} rows; assign them to a user manually before running this migration"
            )


def upgrade():
    _require_empty("cases", "reports")

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.add_column("cases", sa.Column("owner_id", sa.BigInteger(), nullable=False))
    op.create_foreign_key("fk_cases_owner_id", "cases", "users", ["owner_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_cases_owner_id", "cases", ["owner_id"])
    op.add_column("cases", sa.Column("patient_name", sa.String(length=200), nullable=False))
    op.add_column("cases", sa.Column("patient_mrn", sa.String(length=64), nullable=True))

    # One report per case, and a report always belongs to a case.
    op.drop_index("ix_reports_case_id", table_name="reports")
    op.drop_constraint("fk_reports_case_id", "reports", type_="foreignkey")
    op.alter_column("reports", "case_id", existing_type=sa.BigInteger(), nullable=False)
    op.create_unique_constraint("uq_reports_case_id", "reports", ["case_id"])
    op.create_foreign_key("fk_reports_case_id", "reports", "cases", ["case_id"], ["id"], ondelete="RESTRICT")


def downgrade():
    op.drop_constraint("fk_reports_case_id", "reports", type_="foreignkey")
    op.drop_constraint("uq_reports_case_id", "reports", type_="unique")
    op.alter_column("reports", "case_id", existing_type=sa.BigInteger(), nullable=True)
    op.create_foreign_key("fk_reports_case_id", "reports", "cases", ["case_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_reports_case_id", "reports", ["case_id"])

    op.drop_column("cases", "patient_mrn")
    op.drop_column("cases", "patient_name")
    op.drop_index("ix_cases_owner_id", table_name="cases")
    op.drop_constraint("fk_cases_owner_id", "cases", type_="foreignkey")
    op.drop_column("cases", "owner_id")
    op.drop_table("users")
