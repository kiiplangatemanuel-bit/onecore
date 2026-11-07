"""Daraja M-Pesa collection and disbursement intents.

Revision ID: 0025_mpesa_payment_intents
Revises: 0024_pos_accounting_bridge
"""
from alembic import op
import sqlalchemy as sa

revision = "0025_mpesa_payment_intents"
down_revision = "0024_pos_accounting_bridge"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mpesa_payment_intents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("pos_payments.id"), nullable=False),
        sa.Column("phone_number", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("checkout_request_id", sa.String(100), nullable=True),
        sa.Column("merchant_request_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("callback_token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="initiating"),
        sa.Column("result_code", sa.String(40), nullable=False, server_default=""),
        sa.Column("result_description", sa.String(500), nullable=False, server_default=""),
        sa.Column("mpesa_receipt_number", sa.String(40), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("payment_id", name="uq_mpesa_payment_source"),
        sa.UniqueConstraint("checkout_request_id", name="uq_mpesa_payment_checkout"),
        sa.UniqueConstraint("callback_token_hash", name="uq_mpesa_payment_callback_token"),
    )
    op.create_index("ix_mpesa_payment_intents_organization_id", "mpesa_payment_intents", ["organization_id"])
    op.create_index("ix_mpesa_payment_intents_branch_id", "mpesa_payment_intents", ["branch_id"])

    op.create_table(
        "mpesa_refund_intents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("refund_id", sa.Integer(), sa.ForeignKey("pos_refunds.id"), nullable=False),
        sa.Column("phone_number", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("conversation_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("originator_conversation_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("callback_token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="initiating"),
        sa.Column("result_code", sa.String(40), nullable=False, server_default=""),
        sa.Column("result_description", sa.String(500), nullable=False, server_default=""),
        sa.Column("mpesa_receipt_number", sa.String(40), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("refund_id", name="uq_mpesa_refund_source"),
        sa.UniqueConstraint("callback_token_hash", name="uq_mpesa_refund_callback_token"),
    )
    op.create_index("ix_mpesa_refund_intents_organization_id", "mpesa_refund_intents", ["organization_id"])
    op.create_index("ix_mpesa_refund_intents_branch_id", "mpesa_refund_intents", ["branch_id"])


def downgrade():
    op.drop_index("ix_mpesa_refund_intents_branch_id", table_name="mpesa_refund_intents")
    op.drop_index("ix_mpesa_refund_intents_organization_id", table_name="mpesa_refund_intents")
    op.drop_table("mpesa_refund_intents")
    op.drop_index("ix_mpesa_payment_intents_branch_id", table_name="mpesa_payment_intents")
    op.drop_index("ix_mpesa_payment_intents_organization_id", table_name="mpesa_payment_intents")
    op.drop_table("mpesa_payment_intents")
