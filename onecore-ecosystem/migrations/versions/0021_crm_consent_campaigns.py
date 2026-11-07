"""CRM consent evidence and campaign recipient preparation.

Revision ID: 0021_crm_consent_campaigns
Revises: 0020_crm_sales_orders
"""
from alembic import op
import sqlalchemy as sa

revision = "0021_crm_consent_campaigns"
down_revision = "0020_crm_sales_orders"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "crm_contact_consents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id"), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False, server_default="marketing"),
        sa.Column("decision", sa.String(12), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("recorded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_crm_contact_consents_organization_id", "crm_contact_consents", ["organization_id"])
    op.create_index("ix_crm_contact_consents_contact_id", "crm_contact_consents", ["contact_id"])
    op.create_index("ix_crm_consent_org_contact_channel", "crm_contact_consents",
                    ["organization_id", "contact_id", "channel", "purpose", "id"])

    op.create_table(
        "crm_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("campaign_number", sa.String(60), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False, server_default="marketing"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_crm_campaigns_organization_id", "crm_campaigns", ["organization_id"])
    op.create_index("ix_crm_campaigns_branch_id", "crm_campaigns", ["branch_id"])
    op.create_index("ix_crm_campaign_org_number", "crm_campaigns",
                    ["organization_id", "campaign_number"], unique=True)

    op.create_table(
        "crm_campaign_recipients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("crm_campaigns.id"), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id"), nullable=False),
        sa.Column("consent_id", sa.Integer(), sa.ForeignKey("crm_contact_consents.id"), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("address_snapshot", sa.String(320), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="prepared"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_crm_campaign_recipients_organization_id", "crm_campaign_recipients", ["organization_id"])
    op.create_index("ix_crm_campaign_recipients_campaign_id", "crm_campaign_recipients", ["campaign_id"])
    op.create_index("ix_crm_campaign_recipients_contact_id", "crm_campaign_recipients", ["contact_id"])
    op.create_index("ix_crm_campaign_recipients_consent_id", "crm_campaign_recipients", ["consent_id"])
    op.create_index("ix_crm_campaign_recipient_unique", "crm_campaign_recipients",
                    ["campaign_id", "contact_id"], unique=True)


def downgrade():
    op.drop_table("crm_campaign_recipients")
    op.drop_table("crm_campaigns")
    op.drop_table("crm_contact_consents")
