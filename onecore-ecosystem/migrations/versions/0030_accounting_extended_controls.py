"""Accounting AP integration, cash-flow classification and refunds.

Revision ID: 0030_accounting_extended_controls
Revises: 0029_sacco_loan_security_merge
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_accounting_extended_controls"
down_revision = "0029_sacco_loan_security_merge"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounting_accounts", sa.Column("cash_flow_category", sa.String(length=20), nullable=True))
    op.add_column("procurement_supplier_invoices", sa.Column(
        "accounting_invoice_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_procurement_supplier_invoice_accounting_invoice",
        "procurement_supplier_invoices", "accounting_invoices",
        ["accounting_invoice_id"], ["id"])
    op.create_index(
        "ix_procurement_supplier_invoice_accounting_invoice",
        "procurement_supplier_invoices", ["accounting_invoice_id"], unique=True)
    op.create_table(
        "accounting_refunds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("accounting_invoices.id"), nullable=False),
        sa.Column("branch_id", sa.String(length=36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("refund_number", sa.String(length=60), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="KES"),
        sa.Column("payment_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id"), nullable=False),
        sa.Column("refund_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_accounting_refund_org_number", "accounting_refunds",
        ["organization_id", "refund_number"], unique=True)
    op.create_index("ix_accounting_refund_org_key", "accounting_refunds",
        ["organization_id", "idempotency_key"], unique=True)
    op.create_index("ix_accounting_refunds_organization_id", "accounting_refunds", ["organization_id"])
    op.create_index("ix_accounting_refunds_invoice_id", "accounting_refunds", ["invoice_id"])
    op.create_index("ix_accounting_refunds_branch_id", "accounting_refunds", ["branch_id"])


def downgrade():
    op.drop_index("ix_accounting_refunds_branch_id", table_name="accounting_refunds")
    op.drop_index("ix_accounting_refunds_invoice_id", table_name="accounting_refunds")
    op.drop_index("ix_accounting_refunds_organization_id", table_name="accounting_refunds")
    op.drop_index("ix_accounting_refund_org_key", table_name="accounting_refunds")
    op.drop_index("ix_accounting_refund_org_number", table_name="accounting_refunds")
    op.drop_table("accounting_refunds")
    op.drop_index("ix_procurement_supplier_invoice_accounting_invoice", table_name="procurement_supplier_invoices")
    op.drop_constraint("fk_procurement_supplier_invoice_accounting_invoice",
        "procurement_supplier_invoices", type_="foreignkey")
    op.drop_column("procurement_supplier_invoices", "accounting_invoice_id")
    op.drop_column("accounting_accounts", "cash_flow_category")
