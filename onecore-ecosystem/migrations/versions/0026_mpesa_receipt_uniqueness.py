"""Prevent reuse of a Safaricom receipt across POS payments or refunds.

Revision ID: 0026_mpesa_receipt_uniqueness
Revises: 0025_mpesa_payment_intents
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_mpesa_receipt_uniqueness"
down_revision = "0025_mpesa_payment_intents"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    payment_duplicates = bind.execute(sa.text(
        "SELECT organization_id, provider_reference, COUNT(*) AS n "
        "FROM pos_payments WHERE method = 'mpesa' AND provider_reference <> '' "
        "GROUP BY organization_id, provider_reference HAVING COUNT(*) > 1"
    )).fetchall()
    refund_duplicates = bind.execute(sa.text(
        "SELECT organization_id, provider_reference, COUNT(*) AS n "
        "FROM pos_refunds WHERE method = 'mpesa' AND provider_reference <> '' "
        "GROUP BY organization_id, provider_reference HAVING COUNT(*) > 1"
    )).fetchall()
    if payment_duplicates or refund_duplicates:
        raise RuntimeError(
            "Duplicate historical M-Pesa receipts exist; reconcile them before applying 0026"
        )
    op.create_index(
        "uq_pos_mpesa_payment_receipt", "pos_payments",
        ["organization_id", "provider_reference"], unique=True,
        postgresql_where=sa.text("method = 'mpesa' AND provider_reference <> ''"),
        sqlite_where=sa.text("method = 'mpesa' AND provider_reference <> ''"),
    )
    op.create_index(
        "uq_pos_mpesa_refund_receipt", "pos_refunds",
        ["organization_id", "provider_reference"], unique=True,
        postgresql_where=sa.text("method = 'mpesa' AND provider_reference <> ''"),
        sqlite_where=sa.text("method = 'mpesa' AND provider_reference <> ''"),
    )


def downgrade():
    op.drop_index("uq_pos_mpesa_refund_receipt", table_name="pos_refunds")
    op.drop_index("uq_pos_mpesa_payment_receipt", table_name="pos_payments")
