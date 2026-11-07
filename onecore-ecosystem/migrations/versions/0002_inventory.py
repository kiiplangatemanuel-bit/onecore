"""Tenant-scoped inventory catalog and append-only stock ledger.

Revision ID: 0002_inventory
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_inventory"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "inventory_products",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("sku", sa.String(80), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(24), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_inventory_products_organization_id", "inventory_products", ["organization_id"])
    op.create_index("ix_inventory_product_org_sku", "inventory_products", ["organization_id", "sku"], unique=True)
    op.create_table(
        "inventory_stock_movements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("quantity_delta", sa.Numeric(18, 3), nullable=False),
        sa.Column("movement_type", sa.String(20), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_inventory_stock_movements_organization_id", "inventory_stock_movements", ["organization_id"])
    op.create_index("ix_inventory_stock_movements_product_id", "inventory_stock_movements", ["product_id"])
    op.create_index("ix_inventory_stock_movements_branch_id", "inventory_stock_movements", ["branch_id"])
    op.create_index("ix_inventory_movement_org_idempotency", "inventory_stock_movements", ["organization_id", "idempotency_key"], unique=True)
    op.create_index("ix_inventory_movement_org_product_branch", "inventory_stock_movements", ["organization_id", "product_id", "branch_id"])


def downgrade():
    op.drop_table("inventory_stock_movements")
    op.drop_table("inventory_products")
