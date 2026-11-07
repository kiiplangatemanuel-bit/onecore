"""Accounting refunds and procurement-to-AP bridge.

Revision ID: 0022_accounting_completion
Revises: 0021_crm_consent_campaigns
"""
from alembic import op
import sqlalchemy as sa

revision = "0022_accounting_completion"
down_revision = "0021_crm_consent_campaigns"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "accounting_refunds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("accounting_invoices.id"), nullable=False),
        sa.Column("credit_note_id", sa.Integer(), sa.ForeignKey("accounting_credit_notes.id"), nullable=False),
        sa.Column("payment_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("refund_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_accounting_refunds_organization_id", "accounting_refunds", ["organization_id"])
    op.create_index("ix_accounting_refunds_invoice_id", "accounting_refunds", ["invoice_id"])
    op.create_index("ix_accounting_refunds_credit_note_id", "accounting_refunds", ["credit_note_id"])
    op.create_index("ix_accounting_refund_org_key", "accounting_refunds", ["organization_id", "idempotency_key"], unique=True)

    op.create_table(
        "accounting_procurement_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("procurement_invoice_id", sa.Integer(), sa.ForeignKey("procurement_supplier_invoices.id"), nullable=False),
        sa.Column("accounting_invoice_id", sa.Integer(), sa.ForeignKey("accounting_invoices.id"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_accounting_procurement_links_organization_id", "accounting_procurement_links", ["organization_id"])
    op.create_index("ix_accounting_procurement_links_procurement_invoice_id", "accounting_procurement_links", ["procurement_invoice_id"])
    op.create_index("ix_accounting_procurement_links_accounting_invoice_id", "accounting_procurement_links", ["accounting_invoice_id"])
    op.create_index("ix_accounting_procurement_link_org_source", "accounting_procurement_links", ["organization_id", "procurement_invoice_id"], unique=True)
    op.create_index("ix_accounting_procurement_link_org_ledger", "accounting_procurement_links", ["organization_id", "accounting_invoice_id"], unique=True)


def downgrade():
    op.drop_index("ix_accounting_procurement_link_org_ledger", table_name="accounting_procurement_links")
    op.drop_index("ix_accounting_procurement_link_org_source", table_name="accounting_procurement_links")
    op.drop_index("ix_accounting_procurement_links_accounting_invoice_id", table_name="accounting_procurement_links")
    op.drop_index("ix_accounting_procurement_links_procurement_invoice_id", table_name="accounting_procurement_links")
    op.drop_index("ix_accounting_procurement_links_organization_id", table_name="accounting_procurement_links")
    op.drop_table("accounting_procurement_links")
    op.drop_index("ix_accounting_refund_org_key", table_name="accounting_refunds")
    op.drop_index("ix_accounting_refunds_credit_note_id", table_name="accounting_refunds")
    op.drop_index("ix_accounting_refunds_invoice_id", table_name="accounting_refunds")
    op.drop_index("ix_accounting_refunds_organization_id", table_name="accounting_refunds")
    op.drop_table("accounting_refunds")
