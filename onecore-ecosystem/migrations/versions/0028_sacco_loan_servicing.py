"""SACCO loan disbursement, installments and repayments.

Revision ID: 0028_sacco_loan_servicing
Revises: 0027_sacco_foundation
"""
from alembic import op
import sqlalchemy as sa

revision = "0028_sacco_loan_servicing"
down_revision = "0027_sacco_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sacco_loans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("sacco_loan_applications.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("sacco_members.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("loan_number", sa.String(40), nullable=False),
        sa.Column("principal", sa.Numeric(18, 2), nullable=False),
        sa.Column("annual_interest_rate", sa.Numeric(8, 4), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=False),
        sa.Column("interest_method", sa.String(16), nullable=False),
        sa.Column("total_interest", sa.Numeric(18, 2), nullable=False),
        sa.Column("outstanding_principal", sa.Numeric(18, 2), nullable=False),
        sa.Column("outstanding_interest", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("disbursement_reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("disbursed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sacco_loans_organization_id", "sacco_loans", ["organization_id"])
    op.create_index("ix_sacco_loans_application_id", "sacco_loans", ["application_id"], unique=True)
    op.create_index("ix_sacco_loans_member_id", "sacco_loans", ["member_id"])
    op.create_index("ix_sacco_loans_branch_id", "sacco_loans", ["branch_id"])
    op.create_index("ix_sacco_loan_org_number", "sacco_loans",
                    ["organization_id", "loan_number"], unique=True)

    op.create_table(
        "sacco_loan_schedules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("loan_id", sa.Integer(), sa.ForeignKey("sacco_loans.id"), nullable=False),
        sa.Column("installment_number", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("principal_due", sa.Numeric(18, 2), nullable=False),
        sa.Column("interest_due", sa.Numeric(18, 2), nullable=False),
        sa.Column("principal_paid", sa.Numeric(18, 2), nullable=False, server_default="0.00"),
        sa.Column("interest_paid", sa.Numeric(18, 2), nullable=False, server_default="0.00"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
    )
    op.create_index("ix_sacco_loan_schedules_organization_id", "sacco_loan_schedules", ["organization_id"])
    op.create_index("ix_sacco_loan_schedules_loan_id", "sacco_loan_schedules", ["loan_id"])
    op.create_index("ix_sacco_loan_schedule_number", "sacco_loan_schedules",
                    ["organization_id", "loan_id", "installment_number"], unique=True)

    op.create_table(
        "sacco_loan_repayments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("loan_id", sa.Integer(), sa.ForeignKey("sacco_loans.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("principal_component", sa.Numeric(18, 2), nullable=False),
        sa.Column("interest_component", sa.Numeric(18, 2), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sacco_loan_repayments_organization_id", "sacco_loan_repayments", ["organization_id"])
    op.create_index("ix_sacco_loan_repayments_loan_id", "sacco_loan_repayments", ["loan_id"])
    op.create_index("ix_sacco_loan_repayment_org_key", "sacco_loan_repayments",
                    ["organization_id", "idempotency_key"], unique=True)


def downgrade():
    op.drop_table("sacco_loan_repayments")
    op.drop_table("sacco_loan_schedules")
    op.drop_table("sacco_loans")
