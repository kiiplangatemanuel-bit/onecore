"""Add optional liability mapping for one-off employee deductions."""
from alembic import op
import sqlalchemy as sa

revision = "0043_payroll_other_deductions_account"
down_revision = "0042_payroll_adjustments"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payroll_accounting_mappings", sa.Column(
        "other_deductions_payable_account_id", sa.Integer(),
        sa.ForeignKey("accounting_accounts.id"), nullable=True
    ))


def downgrade():
    op.drop_column("payroll_accounting_mappings", "other_deductions_payable_account_id")
