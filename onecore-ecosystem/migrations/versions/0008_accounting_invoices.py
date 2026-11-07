"""Accounts receivable/payable invoices and settlement ledger.

Revision ID: 0008_accounting_invoices
Revises: 0007_school
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_accounting_invoices"
down_revision = "0007_school"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "accounting_invoices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("invoice_type", sa.String(12), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id"), nullable=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("procurement_suppliers.id"), nullable=True),
        sa.Column("invoice_number", sa.String(60), nullable=False),
        sa.Column("issue_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("control_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("total", sa.Numeric(18, 2), nullable=False),
        sa.Column("amount_paid", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id"), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("posted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_accounting_invoices_organization_id", "accounting_invoices", ["organization_id"])
    op.create_index("ix_accounting_invoices_branch_id", "accounting_invoices", ["branch_id"])
    op.create_index("ix_accounting_invoices_contact_id", "accounting_invoices", ["contact_id"])
    op.create_index("ix_accounting_invoices_supplier_id", "accounting_invoices", ["supplier_id"])
    op.create_index("ix_accounting_invoice_org_number", "accounting_invoices", ["organization_id", "invoice_number"], unique=True)
    op.create_index("ix_accounting_invoice_org_status_due", "accounting_invoices", ["organization_id", "status", "due_date"])

    op.create_table(
        "accounting_invoice_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("accounting_invoices.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("tax_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=True),
        sa.Column("description", sa.String(240), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_rate", sa.Numeric(7, 4), nullable=False),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("total", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_accounting_invoice_lines_organization_id", "accounting_invoice_lines", ["organization_id"])
    op.create_index("ix_accounting_invoice_lines_invoice_id", "accounting_invoice_lines", ["invoice_id"])

    op.create_table(
        "accounting_invoice_payments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("accounting_invoices.id"), nullable=False),
        sa.Column("payment_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("payment_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_accounting_invoice_payments_organization_id", "accounting_invoice_payments", ["organization_id"])
    op.create_index("ix_accounting_invoice_payments_invoice_id", "accounting_invoice_payments", ["invoice_id"])
    op.create_index("ix_accounting_invoice_payment_org_idempotency", "accounting_invoice_payments", ["organization_id", "idempotency_key"], unique=True)


def downgrade():
    op.drop_table("accounting_invoice_payments")
    op.drop_table("accounting_invoice_lines")
    op.drop_table("accounting_invoices")
