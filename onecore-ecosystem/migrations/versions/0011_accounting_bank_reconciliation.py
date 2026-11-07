"""Bank statement import and reconciliation matches.

Revision ID: 0011_accounting_bank_reconciliation
Revises: 0010_accounting_depreciation
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_accounting_bank_reconciliation"
down_revision = "0010_accounting_depreciation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("accounting_bank_statements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("statement_reference", sa.String(80), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opening_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("closing_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reconciled_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_accounting_bank_statements_organization_id", "accounting_bank_statements", ["organization_id"])
    op.create_index("ix_accounting_bank_statements_bank_account_id", "accounting_bank_statements", ["bank_account_id"])
    op.create_index("ix_accounting_bank_statements_branch_id", "accounting_bank_statements", ["branch_id"])
    op.create_index("ix_accounting_bank_statement_org_ref", "accounting_bank_statements", ["organization_id", "statement_reference"], unique=True)

    op.create_table("accounting_bank_statement_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("statement_id", sa.Integer(), sa.ForeignKey("accounting_bank_statements.id"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.String(240), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("matched_journal_line_id", sa.Integer(), sa.ForeignKey("accounting_journal_lines.id"), nullable=True),
        sa.Column("matched_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_accounting_bank_statement_lines_organization_id", "accounting_bank_statement_lines", ["organization_id"])
    op.create_index("ix_accounting_bank_statement_lines_statement_id", "accounting_bank_statement_lines", ["statement_id"])
    op.create_index("ix_accounting_bank_statement_line_number", "accounting_bank_statement_lines", ["statement_id", "line_number"], unique=True)
    op.create_index("ix_accounting_bank_match_org_journal", "accounting_bank_statement_lines", ["organization_id", "matched_journal_line_id"], unique=True)


def downgrade():
    op.drop_table("accounting_bank_statement_lines")
    op.drop_table("accounting_bank_statements")
