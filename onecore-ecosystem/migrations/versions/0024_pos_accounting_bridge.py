"""POS-to-accounting mapping and idempotent journal links.

Revision ID: 0024_pos_accounting_bridge
Revises: 0023_pos_tax_discounts
"""
from alembic import op
import sqlalchemy as sa

revision = "0024_pos_accounting_bridge"
down_revision = "0023_pos_tax_discounts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pos_accounting_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("cash_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("card_clearing_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("bank_clearing_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("credit_receivable_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("sales_revenue_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("sales_discount_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("output_tax_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=True),
        sa.Column("sales_returns_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", name="uq_pos_accounting_mapping_org"),
    )
    op.create_index("ix_pos_accounting_mappings_organization_id", "pos_accounting_mappings", ["organization_id"])
    op.create_table(
        "pos_accounting_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id"), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("failure_reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pos_accounting_links_organization_id", "pos_accounting_links", ["organization_id"])
    op.create_index("ix_pos_accounting_links_branch_id", "pos_accounting_links", ["branch_id"])
    op.create_index("ix_pos_accounting_source", "pos_accounting_links",
                    ["organization_id", "source_type", "source_id"], unique=True)
    op.create_index("ix_pos_accounting_pending", "pos_accounting_links",
                    ["organization_id", "status"])


def downgrade():
    op.drop_index("ix_pos_accounting_pending", table_name="pos_accounting_links")
    op.drop_index("ix_pos_accounting_source", table_name="pos_accounting_links")
    op.drop_index("ix_pos_accounting_links_branch_id", table_name="pos_accounting_links")
    op.drop_index("ix_pos_accounting_links_organization_id", table_name="pos_accounting_links")
    op.drop_table("pos_accounting_links")
    op.drop_index("ix_pos_accounting_mappings_organization_id", table_name="pos_accounting_mappings")
    op.drop_table("pos_accounting_mappings")
