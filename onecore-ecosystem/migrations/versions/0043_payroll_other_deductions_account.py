"""Add optional liability mapping for one-off employee deductions."""
from alembic import op
import sqlalchemy as sa

revision = "0043_payroll_other_ded_account"
down_revision = "0042_payroll_adjustments"
branch_labels = None
depends_on = None


def upgrade():
    # Batch mode is required for SQLite's table-copy implementation of ALTER.
    with op.batch_alter_table("payroll_accounting_mappings") as batch_op:
        batch_op.add_column(sa.Column(
            "other_deductions_payable_account_id", sa.Integer(),
            sa.ForeignKey("accounting_accounts.id", name="fk_payroll_mapping_other_deductions_account"), nullable=True
        ))


def downgrade():
    with op.batch_alter_table("payroll_accounting_mappings") as batch_op:
        batch_op.drop_column("other_deductions_payable_account_id")
