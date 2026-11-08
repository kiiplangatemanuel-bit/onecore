"""Allow cancelled payroll runs to release their monthly period key."""
from alembic import op
import sqlalchemy as sa

revision = "0039_payroll_cancelled_period_reuse"
down_revision = "0038_payroll_accounting_bridge"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("uq_payroll_run_org_branch_period", table_name="payroll_runs")
    op.drop_index("uq_payroll_run_org_all_period", table_name="payroll_runs")
    op.create_index("uq_payroll_run_org_branch_period", "payroll_runs",
        ["organization_id", "branch_id", "period_start", "period_end"], unique=True,
        sqlite_where=sa.text("branch_id IS NOT NULL AND status <> 'cancelled'"),
        postgresql_where=sa.text("branch_id IS NOT NULL AND status <> 'cancelled'"))
    op.create_index("uq_payroll_run_org_all_period", "payroll_runs",
        ["organization_id", "period_start", "period_end"], unique=True,
        sqlite_where=sa.text("branch_id IS NULL AND status <> 'cancelled'"),
        postgresql_where=sa.text("branch_id IS NULL AND status <> 'cancelled'"))


def downgrade():
    op.drop_index("uq_payroll_run_org_branch_period", table_name="payroll_runs")
    op.drop_index("uq_payroll_run_org_all_period", table_name="payroll_runs")
    op.create_index("uq_payroll_run_org_branch_period", "payroll_runs",
        ["organization_id", "branch_id", "period_start", "period_end"], unique=True,
        sqlite_where=sa.text("branch_id IS NOT NULL"),
        postgresql_where=sa.text("branch_id IS NOT NULL"))
    op.create_index("uq_payroll_run_org_all_period", "payroll_runs",
        ["organization_id", "period_start", "period_end"], unique=True,
        sqlite_where=sa.text("branch_id IS NULL"),
        postgresql_where=sa.text("branch_id IS NULL"))
