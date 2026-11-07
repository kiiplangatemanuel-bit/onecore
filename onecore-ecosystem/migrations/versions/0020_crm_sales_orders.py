"""CRM accepted quote to sales order conversion.

Revision ID: 0020_crm_sales_orders
Revises: 0019_school_learner_placements
"""
from alembic import op
import sqlalchemy as sa

revision = "0020_crm_sales_orders"
down_revision = "0019_school_learner_placements"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "crm_sales_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("quote_id", sa.Integer(), sa.ForeignKey("crm_quotes.id"), nullable=False, unique=True),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id"), nullable=False),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("crm_leads.id"), nullable=True),
        sa.Column("order_number", sa.String(60), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("total", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="confirmed"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_crm_sales_orders_organization_id", "crm_sales_orders", ["organization_id"])
    op.create_index("ix_crm_sales_orders_branch_id", "crm_sales_orders", ["branch_id"])
    op.create_index("ix_crm_sales_orders_quote_id", "crm_sales_orders", ["quote_id"], unique=True)
    op.create_index("ix_crm_sales_orders_contact_id", "crm_sales_orders", ["contact_id"])
    op.create_index("ix_crm_sales_orders_lead_id", "crm_sales_orders", ["lead_id"])
    op.create_index("ix_crm_sales_order_org_number", "crm_sales_orders",
                    ["organization_id", "order_number"], unique=True)

    op.create_table(
        "crm_sales_order_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), sa.ForeignKey("crm_sales_orders.id"), nullable=False),
        sa.Column("quote_line_id", sa.Integer(), sa.ForeignKey("crm_quote_lines.id"), nullable=False),
        sa.Column("description", sa.String(240), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_rate", sa.Numeric(7, 4), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("total", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_crm_sales_order_lines_organization_id", "crm_sales_order_lines", ["organization_id"])
    op.create_index("ix_crm_sales_order_lines_sales_order_id", "crm_sales_order_lines", ["sales_order_id"])
    op.create_index("ix_crm_sales_order_lines_quote_line_id", "crm_sales_order_lines", ["quote_line_id"])


def downgrade():
    op.drop_table("crm_sales_order_lines")
    op.drop_table("crm_sales_orders")
