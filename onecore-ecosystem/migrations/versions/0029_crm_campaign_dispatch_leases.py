"""Recoverable campaign dispatch leases.

Revision ID: 0029_crm_campaign_dispatch_leases
Revises: 0028_crm_campaign_delivery
"""
from alembic import op
import sqlalchemy as sa

revision = "0029_crm_campaign_dispatch_leases"
down_revision = "0028_crm_campaign_delivery"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "crm_campaign_recipients",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_crm_campaign_recipient_claimed",
        "crm_campaign_recipients",
        ["organization_id", "campaign_id", "status", "claimed_at"],
    )


def downgrade():
    op.drop_index(
        "ix_crm_campaign_recipient_claimed",
        table_name="crm_campaign_recipients",
    )
    op.drop_column("crm_campaign_recipients", "claimed_at")
