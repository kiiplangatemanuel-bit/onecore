"""Supplier, purchase order and goods-receipt foundation.

Revision ID: 0005_procurement
Revises: 0004_crm
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_procurement"
down_revision = "0004_crm"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "procurement_suppliers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("tax_pin", sa.String(24), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_suppliers_organization_id", "procurement_suppliers", ["organization_id"])
    op.create_index("ix_procurement_supplier_org_name", "procurement_suppliers", ["organization_id", "name"])

    op.create_table(
        "procurement_purchase_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("procurement_suppliers.id"), nullable=False),
        sa.Column("order_number", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("notes", sa.String(1000), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_purchase_orders_organization_id", "procurement_purchase_orders", ["organization_id"])
    op.create_index("ix_procurement_purchase_orders_branch_id", "procurement_purchase_orders", ["branch_id"])
    op.create_index("ix_procurement_purchase_orders_supplier_id", "procurement_purchase_orders", ["supplier_id"])
    op.create_index("ix_procurement_po_org_number", "procurement_purchase_orders", ["organization_id", "order_number"], unique=True)

    op.create_table(
        "procurement_purchase_order_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("procurement_purchase_orders.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("quantity_ordered", sa.Numeric(18, 3), nullable=False),
        sa.Column("quantity_received", sa.Numeric(18, 3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_purchase_order_lines_organization_id", "procurement_purchase_order_lines", ["organization_id"])
    op.create_index("ix_procurement_purchase_order_lines_purchase_order_id", "procurement_purchase_order_lines", ["purchase_order_id"])
    op.create_index("ix_procurement_purchase_order_lines_product_id", "procurement_purchase_order_lines", ["product_id"])


def downgrade():
    op.drop_table("procurement_purchase_order_lines")
    op.drop_table("procurement_purchase_orders")
    op.drop_table("procurement_suppliers")
