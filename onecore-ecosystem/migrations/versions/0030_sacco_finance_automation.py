"""SACCO recurring collections, payment reconciliation and finance workflows.

Revision ID: 0030_sacco_finance_automation
Revises: 0029_sacco_loan_security_merge
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_sacco_finance_automation"
down_revision = "0029_sacco_loan_security_merge"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sacco_finance_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("record_type", sa.String(40), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("sacco_members.id"), nullable=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("sacco_accounts.id"), nullable=True),
        sa.Column("loan_id", sa.Integer(), sa.ForeignKey("sacco_loans.id"), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("organization_id", "branch_id", "record_type", "member_id", "account_id", "loan_id"):
        op.create_index(f"ix_sacco_finance_records_{col}", "sacco_finance_records", [col])
    op.create_index("ix_sacco_finance_org_idempotency", "sacco_finance_records",
                    ["organization_id", "idempotency_key"], unique=True)


def downgrade():
    op.drop_table("sacco_finance_records")
