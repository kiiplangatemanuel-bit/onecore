"""Fiscal periods, budgets and fixed asset register.

Revision ID: 0009_accounting_controls
Revises: 0008_accounting_invoices
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_accounting_controls"
down_revision = "0008_accounting_invoices"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("accounting_fiscal_periods",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("closed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_accounting_fiscal_periods_organization_id", "accounting_fiscal_periods", ["organization_id"])
    op.create_index("ix_accounting_period_org_code", "accounting_fiscal_periods", ["organization_id", "code"], unique=True)

    op.create_table("accounting_budgets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("fiscal_period_id", sa.Integer(), sa.ForeignKey("accounting_fiscal_periods.id"), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_accounting_budgets_organization_id", "accounting_budgets", ["organization_id"])
    op.create_index("ix_accounting_budgets_fiscal_period_id", "accounting_budgets", ["fiscal_period_id"])

    op.create_table("accounting_budget_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("budget_id", sa.Integer(), sa.ForeignKey("accounting_budgets.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_accounting_budget_lines_organization_id", "accounting_budget_lines", ["organization_id"])
    op.create_index("ix_accounting_budget_lines_budget_id", "accounting_budget_lines", ["budget_id"])
    op.create_index("ix_accounting_budget_lines_branch_id", "accounting_budget_lines", ["branch_id"])

    op.create_table("accounting_fixed_assets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("asset_code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("acquisition_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("salvage_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("useful_life_months", sa.Integer(), nullable=False),
        sa.Column("accumulated_depreciation", sa.Numeric(18, 2), nullable=False),
        sa.Column("asset_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("accumulated_depreciation_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("depreciation_expense_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_accounting_fixed_assets_organization_id", "accounting_fixed_assets", ["organization_id"])
    op.create_index("ix_accounting_fixed_assets_branch_id", "accounting_fixed_assets", ["branch_id"])
    op.create_index("ix_accounting_fixed_asset_org_code", "accounting_fixed_assets", ["organization_id", "asset_code"], unique=True)


def downgrade():
    op.drop_table("accounting_fixed_assets")
    op.drop_table("accounting_budget_lines")
    op.drop_table("accounting_budgets")
    op.drop_table("accounting_fiscal_periods")
