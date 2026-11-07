"""Goods receipt inspection and accepted-stock posting.

Revision ID: 0015_procurement_grn_inspection
Revises: 0014_procurement_requisitions
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_procurement_grn_inspection"
down_revision = "0014_procurement_requisitions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "procurement_goods_receipts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("procurement_purchase_orders.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("receipt_number", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("received_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("inspected_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("inspected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inspection_note", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_goods_receipts_organization_id", "procurement_goods_receipts", ["organization_id"])
    op.create_index("ix_procurement_goods_receipts_purchase_order_id", "procurement_goods_receipts", ["purchase_order_id"])
    op.create_index("ix_procurement_goods_receipts_branch_id", "procurement_goods_receipts", ["branch_id"])
    op.create_index("ix_procurement_grn_org_number", "procurement_goods_receipts", ["organization_id", "receipt_number"], unique=True)
    op.create_table(
        "procurement_goods_receipt_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("goods_receipt_id", sa.Integer(), sa.ForeignKey("procurement_goods_receipts.id"), nullable=False),
        sa.Column("purchase_order_line_id", sa.Integer(), sa.ForeignKey("procurement_purchase_order_lines.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("quantity_received", sa.Numeric(18, 3), nullable=False),
        sa.Column("quantity_accepted", sa.Numeric(18, 3), nullable=False),
        sa.Column("quantity_rejected", sa.Numeric(18, 3), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("rejection_reason", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_goods_receipt_lines_organization_id", "procurement_goods_receipt_lines", ["organization_id"])
    op.create_index("ix_procurement_goods_receipt_lines_goods_receipt_id", "procurement_goods_receipt_lines", ["goods_receipt_id"])
    op.create_index("ix_procurement_goods_receipt_lines_purchase_order_line_id", "procurement_goods_receipt_lines", ["purchase_order_line_id"])
    op.create_index("ix_procurement_goods_receipt_lines_product_id", "procurement_goods_receipt_lines", ["product_id"])
    op.create_index("ix_procurement_grn_line_org_key", "procurement_goods_receipt_lines", ["organization_id", "idempotency_key"], unique=True)


def downgrade():
    op.drop_table("procurement_goods_receipt_lines")
    op.drop_table("procurement_goods_receipts")
