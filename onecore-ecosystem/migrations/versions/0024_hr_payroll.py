"""HR payroll profiles, draft runs and approved payslip snapshots.

Revision ID: 0024_hr_payroll
Revises: 0023_hr_attendance
"""
from alembic import op
import sqlalchemy as sa

revision = "0024_hr_payroll"
down_revision = "0023_hr_attendance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hr_payroll_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr_employees.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("base_period_pay", sa.Numeric(18, 2), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hr_payroll_profiles_organization_id", "hr_payroll_profiles", ["organization_id"])
    op.create_index("ix_hr_payroll_profiles_employee_id", "hr_payroll_profiles", ["employee_id"])
    op.create_index("ix_hr_payroll_profiles_branch_id", "hr_payroll_profiles", ["branch_id"])
    op.create_index("ix_hr_pay_profile_org_employee_from", "hr_payroll_profiles",
                    ["organization_id", "employee_id", "effective_from"], unique=True)

    op.create_table(
        "hr_payroll_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("run_number", sa.String(40), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("pay_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("gross_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("deductions_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hr_payroll_runs_organization_id", "hr_payroll_runs", ["organization_id"])
    op.create_index("ix_hr_payroll_run_org_period", "hr_payroll_runs",
                    ["organization_id", "period_start", "period_end"], unique=True)
    op.create_index("ix_hr_payroll_run_org_number", "hr_payroll_runs",
                    ["organization_id", "run_number"], unique=True)

    op.create_table(
        "hr_payroll_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("hr_payroll_runs.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr_employees.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("employee_number", sa.String(40), nullable=False),
        sa.Column("employee_name", sa.String(201), nullable=False),
        sa.Column("department", sa.String(120), nullable=False, server_default=""),
        sa.Column("job_title", sa.String(120), nullable=False, server_default=""),
        sa.Column("base_pay", sa.Numeric(18, 2), nullable=False),
        sa.Column("gross_pay", sa.Numeric(18, 2), nullable=False),
        sa.Column("deductions_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_pay", sa.Numeric(18, 2), nullable=False),
    )
    op.create_index("ix_hr_payroll_lines_organization_id", "hr_payroll_lines", ["organization_id"])
    op.create_index("ix_hr_payroll_lines_run_id", "hr_payroll_lines", ["run_id"])
    op.create_index("ix_hr_payroll_lines_employee_id", "hr_payroll_lines", ["employee_id"])
    op.create_index("ix_hr_payroll_lines_branch_id", "hr_payroll_lines", ["branch_id"])
    op.create_index("ix_hr_payroll_line_run_employee", "hr_payroll_lines",
                    ["organization_id", "run_id", "employee_id"], unique=True)

    op.create_table(
        "hr_payroll_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("hr_payroll_runs.id"), nullable=False),
        sa.Column("payroll_line_id", sa.Integer(), sa.ForeignKey("hr_payroll_lines.id"), nullable=False),
        sa.Column("item_type", sa.String(12), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("description", sa.String(180), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("client_item_id", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hr_payroll_items_organization_id", "hr_payroll_items", ["organization_id"])
    op.create_index("ix_hr_payroll_items_run_id", "hr_payroll_items", ["run_id"])
    op.create_index("ix_hr_payroll_items_payroll_line_id", "hr_payroll_items", ["payroll_line_id"])
    op.create_index("ix_hr_payroll_item_org_client_id", "hr_payroll_items",
                    ["organization_id", "client_item_id"], unique=True)


def downgrade():
    op.drop_table("hr_payroll_items")
    op.drop_table("hr_payroll_lines")
    op.drop_table("hr_payroll_runs")
    op.drop_table("hr_payroll_profiles")
