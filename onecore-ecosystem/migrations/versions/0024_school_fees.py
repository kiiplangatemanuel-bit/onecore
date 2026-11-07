"""School fee schedules, learner charges and receipts.

Revision ID: 0024_school_fees
Revises: 0023_hr_attendance
"""
from alembic import op
import sqlalchemy as sa

revision = "0024_school_fees"
down_revision = "0023_hr_attendance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "school_fee_structures",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("school_classes.id"), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("description", sa.String(180), nullable=False),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("term", sa.String(24), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_school_fee_structures_organization_id", "school_fee_structures", ["organization_id"])
    op.create_index("ix_school_fee_structures_branch_id", "school_fee_structures", ["branch_id"])
    op.create_index("ix_school_fee_structures_class_id", "school_fee_structures", ["class_id"])
    op.create_index("ix_school_fee_structure_org_class_year_term_code", "school_fee_structures",
                    ["organization_id", "class_id", "academic_year", "term", "code"], unique=True)

    op.create_table(
        "school_fee_charges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("learner_id", sa.Integer(), sa.ForeignKey("school_learners.id"), nullable=False),
        sa.Column("fee_structure_id", sa.Integer(), sa.ForeignKey("school_fee_structures.id"), nullable=False),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("term", sa.String(24), nullable=False),
        sa.Column("description", sa.String(180), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("amount_paid", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="unpaid"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_school_fee_charges_organization_id", "school_fee_charges", ["organization_id"])
    op.create_index("ix_school_fee_charges_branch_id", "school_fee_charges", ["branch_id"])
    op.create_index("ix_school_fee_charges_learner_id", "school_fee_charges", ["learner_id"])
    op.create_index("ix_school_fee_charges_fee_structure_id", "school_fee_charges", ["fee_structure_id"])
    op.create_index("ix_school_fee_charge_org_learner_structure", "school_fee_charges",
                    ["organization_id", "learner_id", "fee_structure_id"], unique=True)

    op.create_table(
        "school_fee_payments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("learner_id", sa.Integer(), sa.ForeignKey("school_learners.id"), nullable=False),
        sa.Column("receipt_number", sa.String(80), nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("recorded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_school_fee_payments_organization_id", "school_fee_payments", ["organization_id"])
    op.create_index("ix_school_fee_payments_branch_id", "school_fee_payments", ["branch_id"])
    op.create_index("ix_school_fee_payments_learner_id", "school_fee_payments", ["learner_id"])
    op.create_index("ix_school_fee_payment_org_receipt", "school_fee_payments",
                    ["organization_id", "receipt_number"], unique=True)

    op.create_table(
        "school_fee_payment_allocations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("school_fee_payments.id"), nullable=False),
        sa.Column("charge_id", sa.Integer(), sa.ForeignKey("school_fee_charges.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_school_fee_payment_allocations_organization_id", "school_fee_payment_allocations", ["organization_id"])
    op.create_index("ix_school_fee_payment_allocations_payment_id", "school_fee_payment_allocations", ["payment_id"])
    op.create_index("ix_school_fee_payment_allocations_charge_id", "school_fee_payment_allocations", ["charge_id"])
    op.create_index("ix_school_fee_allocation_org_payment_charge", "school_fee_payment_allocations",
                    ["organization_id", "payment_id", "charge_id"], unique=True)


def downgrade():
    op.drop_table("school_fee_payment_allocations")
    op.drop_table("school_fee_payments")
    op.drop_table("school_fee_charges")
    op.drop_table("school_fee_structures")
