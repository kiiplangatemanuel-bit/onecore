"""HR employee directory and leave request workflow.

Revision ID: 0022_hr_employee_leave
Revises: 0021_crm_consent_campaigns
"""
from alembic import op
import sqlalchemy as sa

revision = "0022_hr_employee_leave"
down_revision = "0021_crm_consent_campaigns"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hr_employees",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("employee_number", sa.String(40), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("department", sa.String(120), nullable=False, server_default=""),
        sa.Column("job_title", sa.String(120), nullable=False, server_default=""),
        sa.Column("employment_type", sa.String(20), nullable=False, server_default="full_time"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hr_employees_organization_id", "hr_employees", ["organization_id"])
    op.create_index("ix_hr_employees_branch_id", "hr_employees", ["branch_id"])
    op.create_index("ix_hr_employees_user_id", "hr_employees", ["user_id"])
    op.create_index("ix_hr_employee_org_number", "hr_employees",
                    ["organization_id", "employee_number"], unique=True)

    op.create_table(
        "hr_leave_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr_employees.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("leave_type", sa.String(24), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("working_days", sa.Numeric(8, 2), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hr_leave_requests_organization_id", "hr_leave_requests", ["organization_id"])
    op.create_index("ix_hr_leave_requests_employee_id", "hr_leave_requests", ["employee_id"])
    op.create_index("ix_hr_leave_requests_branch_id", "hr_leave_requests", ["branch_id"])


def downgrade():
    op.drop_table("hr_leave_requests")
    op.drop_table("hr_employees")
