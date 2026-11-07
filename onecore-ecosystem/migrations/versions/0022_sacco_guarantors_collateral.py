"""Persist SACCO loan guarantor and collateral records.

Revision ID: 0022_sacco_guarantors_collateral
Revises: 0021_crm_consent_campaigns
"""
from alembic import op
import sqlalchemy as sa

revision = "0022_sacco_guarantors_collateral"
down_revision = "0021_crm_consent_campaigns"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sacco_loan_guarantors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("loan_id", sa.Integer(), sa.ForeignKey("sacco_loans.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("sacco_members.id"), nullable=False),
        sa.Column("guaranteed_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("consent_reference", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("review_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sacco_loan_guarantors_organization_id", "sacco_loan_guarantors", ["organization_id"])
    op.create_index("ix_sacco_loan_guarantors_loan_id", "sacco_loan_guarantors", ["loan_id"])
    op.create_index("ix_sacco_loan_guarantors_member_id", "sacco_loan_guarantors", ["member_id"])
    op.create_index("ix_sacco_guarantor_org_loan_member", "sacco_loan_guarantors",
                    ["organization_id", "loan_id", "member_id"], unique=True)
    op.create_index("ix_sacco_guarantor_org_loan_status", "sacco_loan_guarantors",
                    ["organization_id", "loan_id", "status"])

    op.create_table(
        "sacco_loan_collateral",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("loan_id", sa.Integer(), sa.ForeignKey("sacco_loans.id"), nullable=False),
        sa.Column("collateral_type", sa.String(40), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("owner_name", sa.String(180), nullable=False),
        sa.Column("identifier", sa.String(120), nullable=False, server_default=""),
        sa.Column("estimated_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("assessed_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("valuation_reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("valuation_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("review_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sacco_loan_collateral_organization_id", "sacco_loan_collateral", ["organization_id"])
    op.create_index("ix_sacco_loan_collateral_loan_id", "sacco_loan_collateral", ["loan_id"])
    op.create_index("ix_sacco_collateral_org_loan_status", "sacco_loan_collateral",
                    ["organization_id", "loan_id", "status"])


def downgrade():
    op.drop_table("sacco_loan_collateral")
    op.drop_table("sacco_loan_guarantors")
