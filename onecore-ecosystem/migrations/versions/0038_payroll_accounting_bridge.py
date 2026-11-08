"""Payroll to accounting chart mappings and reversible journal links."""
from alembic import op
import sqlalchemy as sa

revision = "0038_payroll_accounting_bridge"
down_revision = "0037_hr_payroll_domain"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("payroll_accounting_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("salary_expense_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("employer_contribution_expense_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("net_payable_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("paye_payable_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("nssf_payable_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("shif_payable_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("housing_levy_payable_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("pension_payable_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_payroll_accounting_mappings_organization_id", "payroll_accounting_mappings", ["organization_id"], unique=True)

    op.create_table("payroll_accounting_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id"), nullable=False),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settlement_journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id")),
        sa.Column("reversal_journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id")),
        sa.Column("reversed_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reversed_at", sa.DateTime(timezone=True)),
        sa.Column("reversal_reason", sa.String(500), nullable=False, server_default=""))
    op.create_index("ix_payroll_accounting_links_organization_id", "payroll_accounting_links", ["organization_id"])
    op.create_index("ix_payroll_accounting_links_payroll_run_id", "payroll_accounting_links", ["payroll_run_id"], unique=True)
    op.create_index("ix_payroll_accounting_links_journal_id", "payroll_accounting_links", ["journal_id"], unique=True)
    op.create_index("uq_payroll_accounting_reversal_journal", "payroll_accounting_links", ["reversal_journal_id"], unique=True)
    op.create_index("uq_payroll_accounting_settlement_journal", "payroll_accounting_links", ["settlement_journal_id"], unique=True)


def downgrade():
    op.drop_table("payroll_accounting_links")
    op.drop_table("payroll_accounting_mappings")
