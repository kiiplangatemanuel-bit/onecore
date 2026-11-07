"""CRM reusable templates, advanced segments and campaign scheduling.

Revision ID: 0030_crm_campaign_automation
Revises: 0029_crm_campaign_dispatch_leases
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_crm_campaign_automation"
down_revision = "0029_crm_campaign_dispatch_leases"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "crm_campaign_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False, server_default="marketing"),
        sa.Column("subject", sa.String(240), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_crm_template_org_name", "crm_campaign_templates",
                    ["organization_id", "name"], unique=True)
    op.create_index("ix_crm_campaign_templates_organization_id", "crm_campaign_templates",
                    ["organization_id"])

    op.create_table(
        "crm_contact_segments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_crm_segment_org_name", "crm_contact_segments",
                    ["organization_id", "name"], unique=True)
    op.create_index("ix_crm_contact_segments_organization_id", "crm_contact_segments",
                    ["organization_id"])
    op.create_index("ix_crm_contact_segments_branch_id", "crm_contact_segments", ["branch_id"])

    with op.batch_alter_table("crm_campaigns") as batch:
        batch.add_column(sa.Column("subject", sa.String(240), nullable=False, server_default=""))
        batch.add_column(sa.Column("template_id", sa.Integer(),
                                   sa.ForeignKey("crm_campaign_templates.id"), nullable=True))
        batch.add_column(sa.Column("segment_id", sa.Integer(),
                                   sa.ForeignKey("crm_contact_segments.id"), nullable=True))
        batch.add_column(sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_crm_campaign_template_id", "crm_campaigns", ["template_id"])
    op.create_index("ix_crm_campaign_segment_id", "crm_campaigns", ["segment_id"])
    op.create_index("ix_crm_campaign_schedule", "crm_campaigns", ["status", "scheduled_at"])


def downgrade():
    op.drop_index("ix_crm_campaign_schedule", table_name="crm_campaigns")
    op.drop_index("ix_crm_campaign_segment_id", table_name="crm_campaigns")
    op.drop_index("ix_crm_campaign_template_id", table_name="crm_campaigns")
    with op.batch_alter_table("crm_campaigns") as batch:
        batch.drop_column("scheduled_at")
        batch.drop_column("segment_id")
        batch.drop_column("template_id")
        batch.drop_column("subject")
    op.drop_table("crm_contact_segments")
    op.drop_table("crm_campaign_templates")
