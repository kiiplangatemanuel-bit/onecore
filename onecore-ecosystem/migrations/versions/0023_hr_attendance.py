"""HR daily attendance sessions.

Revision ID: 0023_hr_attendance
Revises: 0022_hr_employee_leave
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_hr_attendance"
down_revision = "0022_hr_employee_leave"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hr_attendance",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr_employees.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("attendance_date", sa.Date(), nullable=False),
        sa.Column("clock_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("clock_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worked_minutes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hr_attendance_organization_id", "hr_attendance", ["organization_id"])
    op.create_index("ix_hr_attendance_employee_id", "hr_attendance", ["employee_id"])
    op.create_index("ix_hr_attendance_branch_id", "hr_attendance", ["branch_id"])
    op.create_index("ix_hr_attendance_org_employee_date", "hr_attendance",
                    ["organization_id", "employee_id", "attendance_date"], unique=True)


def downgrade():
    op.drop_table("hr_attendance")
