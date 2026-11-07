"""POS product tax, sale discount and return allocation snapshots.

Revision ID: 0023_pos_tax_discounts
Revises: 0022_accounting_completion
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_pos_tax_discounts"
down_revision = "0022_accounting_completion"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("inventory_products", sa.Column("tax_rate", sa.Numeric(7, 4), nullable=False, server_default="0"))
    op.add_column("pos_sales", sa.Column("subtotal_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("pos_sales", sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("pos_sales", sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("pos_sale_lines", sa.Column("discount_percent", sa.Numeric(7, 4), nullable=False, server_default="0"))
    op.add_column("pos_sale_lines", sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("pos_sale_lines", sa.Column("tax_rate", sa.Numeric(7, 4), nullable=False, server_default="0"))
    op.add_column("pos_sale_lines", sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("pos_return_lines", sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("pos_return_lines", sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("pos_return_lines", "tax_amount")
    op.drop_column("pos_return_lines", "discount_amount")
    op.drop_column("pos_sale_lines", "tax_amount")
    op.drop_column("pos_sale_lines", "tax_rate")
    op.drop_column("pos_sale_lines", "discount_amount")
    op.drop_column("pos_sale_lines", "discount_percent")
    op.drop_column("pos_sales", "tax_amount")
    op.drop_column("pos_sales", "discount_amount")
    op.drop_column("pos_sales", "subtotal_amount")
    op.drop_column("inventory_products", "tax_rate")
