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
    # Batch mode supports SQLite test/development databases and PostgreSQL.
    with op.batch_alter_table("pos_sales") as batch:
        batch.add_column(sa.Column("customer_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_pos_sales_customer_id", "pos_customers", ["customer_id"], ["id"])
        batch.create_index("ix_pos_sales_customer_id", ["customer_id"])


def downgrade():
    with op.batch_alter_table("pos_sales") as batch:
        batch.drop_index("ix_pos_sales_customer_id")
        batch.drop_constraint("fk_pos_sales_customer_id", type_="foreignkey")
        batch.drop_column("customer_id")
