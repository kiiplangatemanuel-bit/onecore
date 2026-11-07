"""CRM campaign delivery history and unsubscribe tokens."""
from alembic import op
import sqlalchemy as sa
revision="0028_crm_campaign_delivery"
down_revision="0027_pos_shift_cash_controls"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("crm_campaign_deliveries",
        sa.Column("id",sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("recipient_id",sa.Integer(),sa.ForeignKey("crm_campaign_recipients.id"),nullable=False),
        sa.Column("attempt_number",sa.Integer(),nullable=False),
        sa.Column("status",sa.String(16),nullable=False),
        sa.Column("provider_message_id",sa.String(180),nullable=True),
        sa.Column("unsubscribe_token_hash",sa.String(64),nullable=True),
        sa.Column("error_message",sa.String(1000),nullable=True),
        sa.Column("accepted_at",sa.DateTime(timezone=True),nullable=True),
        sa.Column("delivered_at",sa.DateTime(timezone=True),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_crm_campaign_deliveries_org","crm_campaign_deliveries",["organization_id"])
    op.create_index("ix_crm_campaign_deliveries_recipient","crm_campaign_deliveries",["recipient_id"])
    op.create_index("ix_crm_campaign_delivery_provider_id","crm_campaign_deliveries",["provider_message_id"])
    op.create_index("ix_crm_campaign_delivery_unsubscribe","crm_campaign_deliveries",["unsubscribe_token_hash"],unique=True)

def downgrade():
    op.drop_table("crm_campaign_deliveries")
