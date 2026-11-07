"""Procurement sourcing, approvals, supplier invoices and returns.

Revision ID: 0016_procurement_completion
Revises: 0015_procurement_grn_inspection
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_procurement_completion"
down_revision = "0015_procurement_grn_inspection"
branch_labels = None
depends_on = None


def _table(name, *columns):
    op.create_table(name, *columns)


def upgrade():
    _table("procurement_approval_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("minimum_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("maximum_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("approval_level", sa.Integer(), nullable=False),
        sa.Column("approver_role", sa.String(40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_procurement_approval_rules_organization_id", "procurement_approval_rules", ["organization_id"])
    op.create_index("ix_procurement_approval_rule_org_level", "procurement_approval_rules", ["organization_id", "approval_level"], unique=True)

    _table("procurement_approval_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("entity_type", sa.String(24), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("approval_level", sa.Integer(), nullable=False),
        sa.Column("approver_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_procurement_approval_actions_organization_id", "procurement_approval_actions", ["organization_id"])
    op.create_index("ix_procurement_approval_action_org_entity_level", "procurement_approval_actions", ["organization_id", "entity_type", "entity_id", "approval_level"], unique=True)

    _table("procurement_rfqs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("rfq_number", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("closing_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.String(1000), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_procurement_rfqs_organization_id", "procurement_rfqs", ["organization_id"])
    op.create_index("ix_procurement_rfqs_branch_id", "procurement_rfqs", ["branch_id"])
    op.create_index("ix_procurement_rfq_org_number", "procurement_rfqs", ["organization_id", "rfq_number"], unique=True)

    _table("procurement_rfq_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("rfq_id", sa.Integer(), sa.ForeignKey("procurement_rfqs.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for col in ("organization_id", "rfq_id"):
        op.create_index("ix_procurement_rfq_lines_" + col, "procurement_rfq_lines", [col])

    _table("procurement_rfq_invitations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("rfq_id", sa.Integer(), sa.ForeignKey("procurement_rfqs.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("procurement_suppliers.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_procurement_rfq_invitations_organization_id", "procurement_rfq_invitations", ["organization_id"])
    op.create_index("ix_procurement_rfq_invitations_rfq_id", "procurement_rfq_invitations", ["rfq_id"])
    op.create_index("ix_procurement_rfq_invitations_supplier_id", "procurement_rfq_invitations", ["supplier_id"])
    op.create_index("ix_procurement_rfq_invitation_unique", "procurement_rfq_invitations", ["rfq_id", "supplier_id"], unique=True)

    _table("procurement_rfq_quotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("rfq_id", sa.Integer(), sa.ForeignKey("procurement_rfqs.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("procurement_suppliers.id"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("delivery_days", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_procurement_rfq_quotes_organization_id", "procurement_rfq_quotes", ["organization_id"])
    op.create_index("ix_procurement_rfq_quotes_rfq_id", "procurement_rfq_quotes", ["rfq_id"])
    op.create_index("ix_procurement_rfq_quotes_supplier_id", "procurement_rfq_quotes", ["supplier_id"])
    op.create_index("ix_procurement_rfq_quote_supplier", "procurement_rfq_quotes", ["organization_id", "rfq_id", "supplier_id"], unique=True)

    _table("procurement_rfq_quote_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("quote_id", sa.Integer(), sa.ForeignKey("procurement_rfq_quotes.id"), nullable=False),
        sa.Column("rfq_line_id", sa.Integer(), sa.ForeignKey("procurement_rfq_lines.id"), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_rate", sa.Numeric(7, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_procurement_rfq_quote_lines_organization_id", "procurement_rfq_quote_lines", ["organization_id"])
    op.create_index("ix_procurement_rfq_quote_lines_quote_id", "procurement_rfq_quote_lines", ["quote_id"])
    op.create_index("ix_procurement_rfq_quote_lines_rfq_line_id", "procurement_rfq_quote_lines", ["rfq_line_id"])

    _table("procurement_supplier_invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("procurement_suppliers.id"), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("procurement_purchase_orders.id"), nullable=False),
        sa.Column("invoice_number", sa.String(80), nullable=False),
        sa.Column("invoice_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("matched_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for col in ("organization_id", "supplier_id", "purchase_order_id"):
        op.create_index("ix_procurement_supplier_invoices_" + col, "procurement_supplier_invoices", [col])
    op.create_index("ix_procurement_invoice_org_supplier_number", "procurement_supplier_invoices", ["organization_id", "supplier_id", "invoice_number"], unique=True)

    _table("procurement_supplier_invoice_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("procurement_supplier_invoices.id"), nullable=False),
        sa.Column("purchase_order_line_id", sa.Integer(), sa.ForeignKey("procurement_purchase_order_lines.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for col in ("organization_id", "invoice_id", "purchase_order_line_id"):
        op.create_index("ix_procurement_supplier_invoice_lines_" + col, "procurement_supplier_invoice_lines", [col])

    _table("procurement_supplier_returns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("goods_receipt_id", sa.Integer(), sa.ForeignKey("procurement_goods_receipts.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("procurement_suppliers.id"), nullable=False),
        sa.Column("return_number", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("credit_note_reference", sa.String(100), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for col in ("organization_id", "goods_receipt_id", "supplier_id"):
        op.create_index("ix_procurement_supplier_returns_" + col, "procurement_supplier_returns", [col])
    op.create_index("ix_procurement_return_org_number", "procurement_supplier_returns", ["organization_id", "return_number"], unique=True)

    _table("procurement_supplier_return_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("return_id", sa.Integer(), sa.ForeignKey("procurement_supplier_returns.id"), nullable=False),
        sa.Column("receipt_line_id", sa.Integer(), sa.ForeignKey("procurement_goods_receipt_lines.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for col in ("organization_id", "return_id", "receipt_line_id"):
        op.create_index("ix_procurement_supplier_return_lines_" + col, "procurement_supplier_return_lines", [col])


def downgrade():
    for table in (
        "procurement_supplier_return_lines", "procurement_supplier_returns",
        "procurement_supplier_invoice_lines", "procurement_supplier_invoices",
        "procurement_rfq_quote_lines", "procurement_rfq_quotes",
        "procurement_rfq_invitations", "procurement_rfq_lines", "procurement_rfqs",
        "procurement_approval_actions", "procurement_approval_rules",
    ):
        op.drop_table(table)
