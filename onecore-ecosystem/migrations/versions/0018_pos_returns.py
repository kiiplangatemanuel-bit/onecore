"""POS returns, returned stock and refund records.

Revision ID: 0018_pos_returns
Revises: 0017_accounting_approvals_credit_notes
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_pos_returns"
down_revision = "0017_accounting_approvals_credit_notes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pos_returns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("sale_id", sa.Integer(), sa.ForeignKey("pos_sales.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("client_return_id", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("refund_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pos_returns_organization_id", "pos_returns", ["organization_id"])
    op.create_index("ix_pos_returns_sale_id", "pos_returns", ["sale_id"])
    op.create_index("ix_pos_returns_branch_id", "pos_returns", ["branch_id"])
    op.create_index("ix_pos_return_org_client_id", "pos_returns",
                    ["organization_id", "client_return_id"], unique=True)

    op.create_table(
        "pos_return_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("return_id", sa.Integer(), sa.ForeignKey("pos_returns.id"), nullable=False),
        sa.Column("sale_line_id", sa.Integer(), sa.ForeignKey("pos_sale_lines.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(18, 2), nullable=False),
    )
    op.create_index("ix_pos_return_lines_organization_id", "pos_return_lines", ["organization_id"])
    op.create_index("ix_pos_return_lines_return_id", "pos_return_lines", ["return_id"])
    op.create_index("ix_pos_return_lines_sale_line_id", "pos_return_lines", ["sale_line_id"])
    op.create_index("ix_pos_return_lines_product_id", "pos_return_lines", ["product_id"])

    op.create_table(
        "pos_refunds",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("return_id", sa.Integer(), sa.ForeignKey("pos_returns.id"), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("provider_reference", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pos_refunds_organization_id", "pos_refunds", ["organization_id"])
    op.create_index("ix_pos_refunds_return_id", "pos_refunds", ["return_id"])


def downgrade():
    op.drop_table("pos_refunds")
    op.drop_table("pos_return_lines")
    op.drop_table("pos_returns")
