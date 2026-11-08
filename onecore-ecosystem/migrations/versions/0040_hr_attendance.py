"""Daily HR attendance with reviewed overtime and idempotent submissions."""
from alembic import op
import sqlalchemy as sa

revision = "0040_hr_attendance"
down_revision = "0039_payroll_cancelled_period_reuse"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hr_attendance_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id")),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr_employees.id"), nullable=False),
        sa.Column("work_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("clock_in", sa.DateTime(timezone=True), nullable=False),
        sa.Column("clock_out", sa.DateTime(timezone=True), nullable=False),
        sa.Column("break_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_minutes", sa.Integer(), nullable=False, server_default="480"),
        sa.Column("worked_minutes", sa.Integer(), nullable=False),
        sa.Column("overtime_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending_approval"),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("decision_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hr_attendance_records_organization_id", "hr_attendance_records", ["organization_id"])
    op.create_index("ix_hr_attendance_records_branch_id", "hr_attendance_records", ["branch_id"])
    op.create_index("ix_hr_attendance_records_employee_id", "hr_attendance_records", ["employee_id"])
    op.create_index("uq_hr_attendance_org_employee_date", "hr_attendance_records",
                    ["organization_id", "employee_id", "work_date"], unique=True)
    op.create_index("uq_hr_attendance_org_idempotency", "hr_attendance_records",
                    ["organization_id", "idempotency_key"], unique=True)


def downgrade():
    op.drop_table("hr_attendance_records")
