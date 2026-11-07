"""SACCO member accounts, savings ledger and loan origination.

Revision ID: 0027_sacco_foundation
Revises: 0026_pharmacy_lab
"""
from alembic import op
import sqlalchemy as sa

revision = "0027_sacco_foundation"
down_revision = "0026_pharmacy_lab"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sacco_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("member_number", sa.String(40), nullable=False),
        sa.Column("full_name", sa.String(180), nullable=False),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("kyc_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sacco_members_organization_id", "sacco_members", ["organization_id"])
    op.create_index("ix_sacco_members_branch_id", "sacco_members", ["branch_id"])
    op.create_index("ix_sacco_member_org_number", "sacco_members",
                    ["organization_id", "member_number"], unique=True)

    op.create_table(
        "sacco_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("sacco_members.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("account_number", sa.String(40), nullable=False),
        sa.Column("account_type", sa.String(20), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sacco_accounts_organization_id", "sacco_accounts", ["organization_id"])
    op.create_index("ix_sacco_accounts_member_id", "sacco_accounts", ["member_id"])
    op.create_index("ix_sacco_accounts_branch_id", "sacco_accounts", ["branch_id"])
    op.create_index("ix_sacco_account_org_number", "sacco_accounts",
                    ["organization_id", "account_number"], unique=True)
    op.create_index("ix_sacco_account_org_member_type", "sacco_accounts",
                    ["organization_id", "member_id", "account_type"])

    op.create_table(
        "sacco_transactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("sacco_accounts.id"), nullable=False),
        sa.Column("transaction_type", sa.String(24), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sacco_transactions_organization_id", "sacco_transactions", ["organization_id"])
    op.create_index("ix_sacco_transactions_account_id", "sacco_transactions", ["account_id"])
    op.create_index("ix_sacco_transaction_org_idempotency", "sacco_transactions",
                    ["organization_id", "idempotency_key"], unique=True)

    op.create_table(
        "sacco_loan_products",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("minimum_principal", sa.Numeric(18, 2), nullable=False),
        sa.Column("maximum_principal", sa.Numeric(18, 2), nullable=False),
        sa.Column("annual_interest_rate", sa.Numeric(8, 4), nullable=False),
        sa.Column("minimum_term_months", sa.Integer(), nullable=False),
        sa.Column("maximum_term_months", sa.Integer(), nullable=False),
        sa.Column("interest_method", sa.String(16), nullable=False, server_default="reducing"),
        sa.Column("requires_guarantor", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sacco_loan_products_organization_id", "sacco_loan_products", ["organization_id"])
    op.create_index("ix_sacco_loan_product_org_code", "sacco_loan_products",
                    ["organization_id", "code"], unique=True)

    op.create_table(
        "sacco_loan_applications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("sacco_members.id"), nullable=False),
        sa.Column("loan_product_id", sa.Integer(), sa.ForeignKey("sacco_loan_products.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("application_number", sa.String(40), nullable=False),
        sa.Column("requested_principal", sa.Numeric(18, 2), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="submitted"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sacco_loan_applications_organization_id", "sacco_loan_applications", ["organization_id"])
    op.create_index("ix_sacco_loan_applications_member_id", "sacco_loan_applications", ["member_id"])
    op.create_index("ix_sacco_loan_applications_loan_product_id", "sacco_loan_applications", ["loan_product_id"])
    op.create_index("ix_sacco_loan_applications_branch_id", "sacco_loan_applications", ["branch_id"])
    op.create_index("ix_sacco_loan_app_org_number", "sacco_loan_applications",
                    ["organization_id", "application_number"], unique=True)


def downgrade():
    op.drop_table("sacco_loan_applications")
    op.drop_table("sacco_loan_products")
    op.drop_table("sacco_transactions")
    op.drop_table("sacco_accounts")
    op.drop_table("sacco_members")
