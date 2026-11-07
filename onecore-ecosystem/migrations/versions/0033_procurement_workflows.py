"""Procurement settlements, delegated approvals, supplier portal and statements."""
from alembic import op
import sqlalchemy as sa

revision = "0033_procurement_workflows"
down_revision = "0032_crm_forecast_attribution"
branch_labels = None
depends_on = None

def _indexes(table, columns, unique=False):
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column], unique=unique and len(columns) == 1)

def upgrade():
    op.create_table(
        "procurement_settlements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("procurement_suppliers.id"), nullable=False),
        sa.Column("payment_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("provider", sa.String(24), nullable=False, server_default="manual"),
        sa.Column("provider_reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("provider_phone_number", sa.String(16), nullable=False, server_default=""),
        sa.Column("callback_token_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("provider_conversation_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("provider_originator_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("provider_result_code", sa.String(40), nullable=False, server_default=""),
        sa.Column("provider_result_description", sa.String(500), nullable=False, server_default=""),
        sa.Column("reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending_verification"),
        sa.Column("payment_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id")),
        sa.Column("verified_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_settlement_org_key", "procurement_settlements", ["organization_id", "idempotency_key"], unique=True)
    op.create_index("ix_procurement_settlements_organization_id", "procurement_settlements", ["organization_id"])
    op.create_index("ix_procurement_settlements_supplier_id", "procurement_settlements", ["supplier_id"])
    op.create_table(
        "procurement_settlement_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("settlement_id", sa.Integer(), sa.ForeignKey("procurement_settlements.id"), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("accounting_invoices.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("accounting_payment_id", sa.Integer(), sa.ForeignKey("accounting_invoice_payments.id")),
    )
    op.create_index("ix_procurement_settlement_allocation_invoice", "procurement_settlement_allocations", ["settlement_id", "invoice_id"], unique=True)
    op.create_index("ix_procurement_settlement_allocations_organization_id", "procurement_settlement_allocations", ["organization_id"])
    op.create_table(
        "procurement_approval_delegations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id")),
        sa.Column("principal_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("delegate_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_delegation_org_principal", "procurement_approval_delegations", ["organization_id", "principal_user_id", "starts_at", "ends_at"])
    op.create_index("ix_procurement_approval_delegations_organization_id", "procurement_approval_delegations", ["organization_id"])
    op.create_index("ix_procurement_approval_delegations_branch_id", "procurement_approval_delegations", ["branch_id"])
    op.create_index("ix_procurement_approval_delegations_principal_user_id", "procurement_approval_delegations", ["principal_user_id"])
    op.create_index("ix_procurement_approval_delegations_delegate_user_id", "procurement_approval_delegations", ["delegate_user_id"])
    op.create_table(
        "procurement_supplier_portal_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("procurement_suppliers.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_supplier_portal_tokens_organization_id", "procurement_supplier_portal_tokens", ["organization_id"])
    op.create_index("ix_procurement_supplier_portal_tokens_supplier_id", "procurement_supplier_portal_tokens", ["supplier_id"])
    op.create_table(
        "procurement_invoice_discrepancies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("supplier_invoice_id", sa.Integer(), sa.ForeignKey("procurement_supplier_invoices.id"), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("resolution_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_invoice_discrepancies_organization_id", "procurement_invoice_discrepancies", ["organization_id"])
    op.create_index("ix_procurement_invoice_discrepancies_supplier_invoice_id", "procurement_invoice_discrepancies", ["supplier_invoice_id"])
    op.create_table(
        "procurement_supplier_statements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("procurement_suppliers.id"), nullable=False),
        sa.Column("statement_reference", sa.String(80), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opening_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("closing_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reconciled_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reconciled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_supplier_statement_org_ref", "procurement_supplier_statements", ["organization_id", "statement_reference"], unique=True)
    op.create_index("ix_procurement_supplier_statements_organization_id", "procurement_supplier_statements", ["organization_id"])
    op.create_index("ix_procurement_supplier_statements_supplier_id", "procurement_supplier_statements", ["supplier_id"])
    op.create_table(
        "procurement_supplier_statement_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("statement_id", sa.Integer(), sa.ForeignKey("procurement_supplier_statements.id"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.String(240), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("matched_invoice_id", sa.Integer(), sa.ForeignKey("accounting_invoices.id")),
        sa.Column("matched_payment_id", sa.Integer(), sa.ForeignKey("accounting_invoice_payments.id")),
        sa.Column("matched_credit_note_id", sa.Integer(), sa.ForeignKey("accounting_credit_notes.id")),
        sa.Column("matched_settlement_id", sa.Integer(), sa.ForeignKey("procurement_settlements.id")),
        sa.Column("matched_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("matched_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_supplier_statement_line_no", "procurement_supplier_statement_lines", ["statement_id", "line_number"], unique=True)
    op.create_index("ix_procurement_supplier_statement_lines_organization_id", "procurement_supplier_statement_lines", ["organization_id"])
    op.create_index("ix_procurement_supplier_statement_lines_statement_id", "procurement_supplier_statement_lines", ["statement_id"])

def downgrade():
    op.drop_table("procurement_supplier_statement_lines")
    op.drop_table("procurement_supplier_statements")
    op.drop_table("procurement_invoice_discrepancies")
    op.drop_table("procurement_supplier_portal_tokens")
    op.drop_table("procurement_approval_delegations")
    op.drop_table("procurement_settlement_allocations")
    op.drop_table("procurement_settlements")
