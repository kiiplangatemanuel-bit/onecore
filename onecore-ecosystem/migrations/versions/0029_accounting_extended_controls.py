"""Accounting statutory summaries, AP links, cash-flow mappings and refunds."""
from alembic import op
import sqlalchemy as sa

revision = "0029_accounting_extended_controls"
down_revision = "0028_sacco_loan_servicing"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounting_accounts", sa.Column("is_cash_equivalent", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("accounting_accounts", sa.Column("cash_flow_category", sa.String(length=16), nullable=True))
    op.add_column("procurement_supplier_invoices", sa.Column("accounting_invoice_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_procurement_supplier_invoice_accounting_invoice",
        "procurement_supplier_invoices", "accounting_invoices", ["accounting_invoice_id"], ["id"])
    op.create_index("ix_procurement_supplier_invoice_accounting_invoice",
        "procurement_supplier_invoices", ["accounting_invoice_id"], unique=True)
    op.create_table(
        "accounting_invoice_refunds",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("accounting_invoices.id"), nullable=False),
        sa.Column("payment_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("refund_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_accounting_invoice_refunds_organization_id", "accounting_invoice_refunds", ["organization_id"])
    op.create_index("ix_accounting_invoice_refunds_invoice_id", "accounting_invoice_refunds", ["invoice_id"])
    op.create_index("ix_accounting_refund_org_key", "accounting_invoice_refunds", ["organization_id", "idempotency_key"], unique=True)


def downgrade():
    op.drop_index("ix_accounting_refund_org_key", table_name="accounting_invoice_refunds")
    op.drop_index("ix_accounting_invoice_refunds_invoice_id", table_name="accounting_invoice_refunds")
    op.drop_index("ix_accounting_invoice_refunds_organization_id", table_name="accounting_invoice_refunds")
    op.drop_table("accounting_invoice_refunds")
    op.drop_index("ix_procurement_supplier_invoice_accounting_invoice", table_name="procurement_supplier_invoices")
    op.drop_constraint("fk_procurement_supplier_invoice_accounting_invoice", "procurement_supplier_invoices", type_="foreignkey")
    op.drop_column("procurement_supplier_invoices", "accounting_invoice_id")
    op.drop_column("accounting_accounts", "cash_flow_category")
    op.drop_column("accounting_accounts", "is_cash_equivalent")
