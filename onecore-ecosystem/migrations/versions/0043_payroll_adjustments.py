"""Add independently approved one-off payroll adjustments."""
from alembic import op
import sqlalchemy as sa

revision = "0043_payroll_adjustments"
down_revision = "0042_payroll_payment_batches"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payroll_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr_employees.id"), nullable=False),
        sa.Column("adjustment_type", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(160), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_payroll_adjustment_org_idempotency"),
    )
    op.create_index("ix_payroll_adjustments_organization_id", "payroll_adjustments", ["organization_id"])
    op.create_index("ix_payroll_adjustments_branch_id", "payroll_adjustments", ["branch_id"])
    op.create_index("ix_payroll_adjustments_employee_id", "payroll_adjustments", ["employee_id"])
    op.create_index("ix_payroll_adjustments_payroll_run_id", "payroll_adjustments", ["payroll_run_id"])
    op.create_index("ix_payroll_adjustment_period_queue", "payroll_adjustments",
                    ["organization_id", "employee_id", "status", "effective_date"])


def downgrade():
    op.drop_index("ix_payroll_adjustment_period_queue", table_name="payroll_adjustments")
    op.drop_index("ix_payroll_adjustments_payroll_run_id", table_name="payroll_adjustments")
    op.drop_index("ix_payroll_adjustments_employee_id", table_name="payroll_adjustments")
    op.drop_index("ix_payroll_adjustments_branch_id", table_name="payroll_adjustments")
    op.drop_index("ix_payroll_adjustments_organization_id", table_name="payroll_adjustments")
    op.drop_table("payroll_adjustments")
