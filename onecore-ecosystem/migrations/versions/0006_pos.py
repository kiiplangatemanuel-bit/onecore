"""POS shifts, checkout and offline idempotent sync.

Revision ID: 0006_pos
Revises: 0005_procurement
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_pos"
down_revision = "0005_procurement"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("inventory_products", sa.Column("sale_price", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.create_table(
        "pos_shifts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("cashier_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("opening_cash", sa.Numeric(18, 2), nullable=False),
        sa.Column("closing_cash", sa.Numeric(18, 2), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pos_shifts_organization_id", "pos_shifts", ["organization_id"])
    op.create_index("ix_pos_shifts_branch_id", "pos_shifts", ["branch_id"])
    op.create_index("ix_pos_shifts_cashier_user_id", "pos_shifts", ["cashier_user_id"])

    op.create_table(
        "pos_sales",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("shift_id", sa.Integer(), sa.ForeignKey("pos_shifts.id"), nullable=False),
        sa.Column("cashier_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_transaction_id", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("offline_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pos_sales_organization_id", "pos_sales", ["organization_id"])
    op.create_index("ix_pos_sales_branch_id", "pos_sales", ["branch_id"])
    op.create_index("ix_pos_sales_shift_id", "pos_sales", ["shift_id"])
    op.create_index("ix_pos_sale_org_client_txn", "pos_sales", ["organization_id", "client_transaction_id"], unique=True)

    op.create_table(
        "pos_sale_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("sale_id", sa.Integer(), sa.ForeignKey("pos_sales.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(18, 2), nullable=False),
    )
    op.create_index("ix_pos_sale_lines_organization_id", "pos_sale_lines", ["organization_id"])
    op.create_index("ix_pos_sale_lines_sale_id", "pos_sale_lines", ["sale_id"])
    op.create_index("ix_pos_sale_lines_product_id", "pos_sale_lines", ["product_id"])

    op.create_table(
        "pos_payments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("sale_id", sa.Integer(), sa.ForeignKey("pos_sales.id"), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("provider_reference", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pos_payments_organization_id", "pos_payments", ["organization_id"])
    op.create_index("ix_pos_payments_sale_id", "pos_payments", ["sale_id"])


def downgrade():
    op.drop_table("pos_payments")
    op.drop_table("pos_sale_lines")
    op.drop_table("pos_sales")
    op.drop_table("pos_shifts")
    op.drop_column("inventory_products", "sale_price")
