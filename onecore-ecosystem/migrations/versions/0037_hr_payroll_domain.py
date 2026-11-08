"""HR employee, leave, versioned statutory payroll and immutable payslips."""
from alembic import op
import sqlalchemy as sa

revision = "0037_hr_payroll_domain"
down_revision = "0036_healthcare_hospital_operations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("hr_employees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id")),
        sa.Column("employee_number", sa.String(60), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(320), nullable=False, server_default=""),
        sa.Column("phone", sa.String(32), nullable=False, server_default=""),
        sa.Column("department", sa.String(120), nullable=False, server_default=""),
        sa.Column("job_title", sa.String(120), nullable=False, server_default=""),
        sa.Column("employment_type", sa.String(24), nullable=False, server_default="permanent"),
        sa.Column("employment_status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("hire_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("termination_date", sa.DateTime(timezone=True)),
        sa.Column("base_salary", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("recurring_allowances", sa.JSON(), nullable=False),
        sa.Column("recurring_benefits", sa.JSON(), nullable=False),
        sa.Column("pension_contribution", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("uq_hr_employee_org_number", "hr_employees", ["organization_id", "employee_number"], unique=True)
    for col in ("organization_id", "branch_id"):
        op.create_index("ix_hr_employees_" + col, "hr_employees", [col])

    op.create_table("hr_leave_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id")),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr_employees.id"), nullable=False),
        sa.Column("leave_type", sa.String(32), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("days", sa.Numeric(7, 2), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("decision_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for col in ("organization_id", "branch_id", "employee_id"):
        op.create_index("ix_hr_leave_requests_" + col, "hr_leave_requests", [col])

    op.create_table("payroll_rule_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("source_evidence", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("uq_payroll_rule_org_version", "payroll_rule_sets", ["organization_id", "version"], unique=True)
    op.create_index("ix_payroll_rule_sets_organization_id", "payroll_rule_sets", ["organization_id"])

    op.create_table("payroll_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id")),
        sa.Column("rule_set_id", sa.Integer(), sa.ForeignKey("payroll_rule_sets.id"), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("employee_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gross_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("deductions_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("employer_cost_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("calculation_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("paid_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("payment_reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("uq_payroll_run_org_idempotency", "payroll_runs", ["organization_id", "idempotency_key"], unique=True)
    op.create_index("uq_payroll_run_org_branch_period", "payroll_runs", ["organization_id", "branch_id", "period_start", "period_end"], unique=True, sqlite_where=sa.text("branch_id IS NOT NULL AND status <> 'cancelled'"), postgresql_where=sa.text("branch_id IS NOT NULL AND status <> 'cancelled'"))
    op.create_index("uq_payroll_run_org_all_period", "payroll_runs", ["organization_id", "period_start", "period_end"], unique=True, sqlite_where=sa.text("branch_id IS NULL AND status <> 'cancelled'"), postgresql_where=sa.text("branch_id IS NULL AND status <> 'cancelled'"))
    for col in ("organization_id", "branch_id"):
        op.create_index("ix_payroll_runs_" + col, "payroll_runs", [col])

    op.create_table("payroll_payslips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr_employees.id"), nullable=False),
        sa.Column("employee_number", sa.String(60), nullable=False),
        sa.Column("employee_name", sa.String(201), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("gross_pay", sa.Numeric(18, 2), nullable=False),
        sa.Column("taxable_pay", sa.Numeric(18, 2), nullable=False),
        sa.Column("paye", sa.Numeric(18, 2), nullable=False),
        sa.Column("nssf_employee", sa.Numeric(18, 2), nullable=False),
        sa.Column("shif_employee", sa.Numeric(18, 2), nullable=False),
        sa.Column("housing_levy_employee", sa.Numeric(18, 2), nullable=False),
        sa.Column("pension_employee", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_deductions", sa.Numeric(18, 2), nullable=False),
        sa.Column("net_pay", sa.Numeric(18, 2), nullable=False),
        sa.Column("nssf_employer", sa.Numeric(18, 2), nullable=False),
        sa.Column("housing_levy_employer", sa.Numeric(18, 2), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("uq_payroll_payslip_run_employee", "payroll_payslips", ["payroll_run_id", "employee_id"], unique=True)
    for col in ("organization_id", "payroll_run_id", "employee_id"):
        op.create_index("ix_payroll_payslips_" + col, "payroll_payslips", [col])


def downgrade():
    op.drop_table("payroll_payslips")
    op.drop_table("payroll_runs")
    op.drop_table("payroll_rule_sets")
    op.drop_table("hr_leave_requests")
    op.drop_table("hr_employees")
