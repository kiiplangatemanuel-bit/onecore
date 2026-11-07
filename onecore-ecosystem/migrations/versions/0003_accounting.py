"""Tenant-scoped chart of accounts and double-entry journals.

Revision ID: 0003_accounting
Revises: 0002_inventory
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_accounting"
down_revision = "0002_inventory"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "accounting_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("account_type", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_accounting_accounts_organization_id", "accounting_accounts", ["organization_id"])
    op.create_index("ix_accounting_account_org_code", "accounting_accounts", ["organization_id", "code"], unique=True)

    op.create_table(
        "accounting_journals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("journal_number", sa.String(40), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False),
        sa.Column("memo", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("entry_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("posted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_accounting_journals_organization_id", "accounting_journals", ["organization_id"])
    op.create_index("ix_accounting_journals_branch_id", "accounting_journals", ["branch_id"])
    op.create_index("ix_accounting_journal_org_number", "accounting_journals", ["organization_id", "journal_number"], unique=True)

    op.create_table(
        "accounting_journal_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("description", sa.String(240), nullable=False),
        sa.Column("debit", sa.Numeric(18, 2), nullable=False),
        sa.Column("credit", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_accounting_journal_lines_organization_id", "accounting_journal_lines", ["organization_id"])
    op.create_index("ix_accounting_journal_lines_journal_id", "accounting_journal_lines", ["journal_id"])
    op.create_index("ix_accounting_journal_lines_account_id", "accounting_journal_lines", ["account_id"])
    op.create_index("ix_accounting_journal_lines_branch_id", "accounting_journal_lines", ["branch_id"])


def downgrade():
    op.drop_table("accounting_journal_lines")
    op.drop_table("accounting_journals")
    op.drop_table("accounting_accounts")
