"""Fixed asset depreciation posting ledger.

Revision ID: 0010_accounting_depreciation
Revises: 0009_accounting_controls
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_accounting_depreciation"
down_revision = "0009_accounting_controls"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("accounting_depreciation_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("accounting_fixed_assets.id"), nullable=False),
        sa.Column("period_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_accounting_depreciation_entries_organization_id", "accounting_depreciation_entries", ["organization_id"])
    op.create_index("ix_accounting_depreciation_entries_asset_id", "accounting_depreciation_entries", ["asset_id"])
    op.create_index("ix_accounting_depreciation_org_key", "accounting_depreciation_entries", ["organization_id", "idempotency_key"], unique=True)
    op.create_index("ix_accounting_depreciation_asset_period", "accounting_depreciation_entries", ["organization_id", "asset_id", "period_date"], unique=True)


def downgrade():
    op.drop_table("accounting_depreciation_entries")
