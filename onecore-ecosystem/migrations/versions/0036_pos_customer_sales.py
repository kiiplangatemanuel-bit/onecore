"""Link POS sales to customer membership records.
Revision ID: 0036
Revises: 0035
"""
from alembic import op
import sqlalchemy as sa

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pos_sales", sa.Column("customer_id", sa.Integer(), sa.ForeignKey("pos_customers.id"), nullable=True))
    op.create_index("ix_pos_sales_customer_id", "pos_sales", ["customer_id"])


def downgrade():
    op.drop_index("ix_pos_sales_customer_id", table_name="pos_sales")
    op.drop_column("pos_sales", "customer_id")
