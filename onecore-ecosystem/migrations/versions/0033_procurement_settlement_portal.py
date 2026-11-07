"""Procurement supplier settlement, portal access and statement reconciliation."""
from alembic import op
import sqlalchemy as sa

revision = "0033_procurement_settlement_portal"
down_revision = "0032_crm_forecast_attribution"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "procurement_settlements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("procurement_suppliers.id"), nullable=False),
        sa.Column("payment_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("provider_reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("payment_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending_verification"),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id"), nullable=True),
        sa.Column("verified_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_settlements_organization_id", "procurement_settlements", ["organization_id"])
    op.create_index("ix_procurement_settlements_supplier_id", "procurement_settlements", ["supplier_id"])
    op.create_index("ix_procurement_settlement_org_key", "procurement_settlements", ["organization_id", "idempotency_key"], unique=True)
    op.create_index("ix_procurement_settlement_org_provider_ref", "procurement_settlements", ["organization_id", "provider", "provider_reference"], unique=True)

    op.create_table(
        "procurement_settlement_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("settlement_id", sa.Integer(), sa.ForeignKey("procurement_settlements.id"), nullable=False),
        sa.Column("accounting_invoice_id", sa.Integer(), sa.ForeignKey("accounting_invoices.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_settlement_allocations_organization_id", "procurement_settlement_allocations", ["organization_id"])
    op.create_index("ix_procurement_settlement_allocations_settlement_id", "procurement_settlement_allocations", ["settlement_id"])
    op.create_index("ix_procurement_settlement_allocations_accounting_invoice_id", "procurement_settlement_allocations", ["accounting_invoice_id"])
    op.create_index("ix_procurement_settlement_allocation_unique", "procurement_settlement_allocations", ["settlement_id", "accounting_invoice_id"], unique=True)

    op.create_table(
        "procurement_supplier_portal_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("procurement_suppliers.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_supplier_portal_tokens_organization_id", "procurement_supplier_portal_tokens", ["organization_id"])
    op.create_index("ix_procurement_supplier_portal_tokens_supplier_id", "procurement_supplier_portal_tokens", ["supplier_id"])

    op.create_table(
        "procurement_supplier_statement_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("procurement_suppliers.id"), nullable=False),
        sa.Column("statement_reference", sa.String(100), nullable=False),
        sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document_reference", sa.String(120), nullable=False),
        sa.Column("description", sa.String(240), nullable=False, server_default=""),
        sa.Column("debit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("credit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("matched_accounting_invoice_id", sa.Integer(), sa.ForeignKey("accounting_invoices.id"), nullable=True),
        sa.Column("matched_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_supplier_statement_lines_organization_id", "procurement_supplier_statement_lines", ["organization_id"])
    op.create_index("ix_procurement_supplier_statement_lines_supplier_id", "procurement_supplier_statement_lines", ["supplier_id"])
    op.create_index("ix_procurement_supplier_statement_ref", "procurement_supplier_statement_lines", ["organization_id", "supplier_id", "statement_reference", "document_reference"], unique=True)


def downgrade():
    op.drop_index("ix_procurement_supplier_statement_ref", table_name="procurement_supplier_statement_lines")
    op.drop_index("ix_procurement_supplier_statement_lines_supplier_id", table_name="procurement_supplier_statement_lines")
    op.drop_index("ix_procurement_supplier_statement_lines_organization_id", table_name="procurement_supplier_statement_lines")
    op.drop_table("procurement_supplier_statement_lines")
    op.drop_index("ix_procurement_supplier_portal_tokens_supplier_id", table_name="procurement_supplier_portal_tokens")
    op.drop_index("ix_procurement_supplier_portal_tokens_organization_id", table_name="procurement_supplier_portal_tokens")
    op.drop_table("procurement_supplier_portal_tokens")
    op.drop_index("ix_procurement_settlement_allocation_unique", table_name="procurement_settlement_allocations")
    op.drop_index("ix_procurement_settlement_allocations_accounting_invoice_id", table_name="procurement_settlement_allocations")
    op.drop_index("ix_procurement_settlement_allocations_settlement_id", table_name="procurement_settlement_allocations")
    op.drop_index("ix_procurement_settlement_allocations_organization_id", table_name="procurement_settlement_allocations")
    op.drop_table("procurement_settlement_allocations")
    op.drop_index("ix_procurement_settlement_org_provider_ref", table_name="procurement_settlements")
    op.drop_index("ix_procurement_settlement_org_key", table_name="procurement_settlements")
    op.drop_index("ix_procurement_settlements_supplier_id", table_name="procurement_settlements")
    op.drop_index("ix_procurement_settlements_organization_id", table_name="procurement_settlements")
    op.drop_table("procurement_settlements")
