"""Shift scheduling, approved attendance and payroll overtime snapshot fields."""
from alembic import op
import sqlalchemy as sa

revision = "0040_hr_attendance_shifts"
down_revision = "0039_payroll_cancelled_period_reuse"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("hr_shifts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id")),
        sa.Column("shift_code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("break_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("differential_rate", sa.Numeric(8, 6), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_hr_shifts_organization_id", "hr_shifts", ["organization_id"])
    op.create_index("ix_hr_shifts_branch_id", "hr_shifts", ["branch_id"])
    op.create_index("uq_hr_shift_org_code", "hr_shifts", ["organization_id", "shift_code"], unique=True)

    op.add_column("hr_employees", sa.Column("default_shift_id", sa.Integer(), sa.ForeignKey("hr_shifts.id")))

    op.create_table("hr_attendance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id")),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr_employees.id"), nullable=False),
        sa.Column("shift_id", sa.Integer(), sa.ForeignKey("hr_shifts.id"), nullable=False),
        sa.Column("attendance_date", sa.Date(), nullable=False),
        sa.Column("clock_in", sa.DateTime(timezone=True)),
        sa.Column("clock_out", sa.DateTime(timezone=True)),
        sa.Column("scheduled_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("worked_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overtime_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("differential_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("differential_rate", sa.Numeric(8, 6), nullable=False, server_default="0"),
        sa.Column("status", sa.String(24), nullable=False, server_default="present"),
        sa.Column("approval_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("notes", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_hr_attendance_organization_id", "hr_attendance", ["organization_id"])
    op.create_index("ix_hr_attendance_branch_id", "hr_attendance", ["branch_id"])
    op.create_index("ix_hr_attendance_employee_id", "hr_attendance", ["employee_id"])
    op.create_index("ix_hr_attendance_attendance_date", "hr_attendance", ["attendance_date"])
    op.create_index("uq_hr_attendance_org_employee_date", "hr_attendance",
                    ["organization_id", "employee_id", "attendance_date"], unique=True)

    op.add_column("payroll_payslips", sa.Column("overtime_pay", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("payroll_payslips", sa.Column("shift_differential_pay", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("payroll_payslips", sa.Column("unpaid_leave_deduction", sa.Numeric(18, 2), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("payroll_payslips", "unpaid_leave_deduction")
    op.drop_column("payroll_payslips", "shift_differential_pay")
    op.drop_column("payroll_payslips", "overtime_pay")
    op.drop_table("hr_attendance")
    op.drop_column("hr_employees", "default_shift_id")
    op.drop_table("hr_shifts")
