"""CRM templates, advanced audiences and scheduled campaign automation.

Revision ID: 0030_crm_automation
Revises: 0029_crm_campaign_dispatch_leases
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_crm_automation"
down_revision = "0029_crm_campaign_dispatch_leases"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("crm_campaign_recipients", sa.Column("subject_snapshot", sa.String(180), nullable=True))
    op.add_column("crm_campaign_recipients", sa.Column("message_snapshot", sa.Text(), nullable=True))
    op.create_table(
        "crm_message_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False, server_default="marketing"),
        sa.Column("subject", sa.String(180), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_crm_message_templates_organization_id", "crm_message_templates", ["organization_id"])
    op.create_index("ix_crm_message_templates_branch_id", "crm_message_templates", ["branch_id"])
    op.create_index("ix_crm_template_org_name_version", "crm_message_templates", ["organization_id", "name", "version"], unique=True)
    op.create_table(
        "crm_audience_segments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_crm_audience_segments_organization_id", "crm_audience_segments", ["organization_id"])
    op.create_index("ix_crm_audience_segments_branch_id", "crm_audience_segments", ["branch_id"])
    op.create_index("ix_crm_segment_org_name", "crm_audience_segments", ["organization_id", "name"], unique=True)
    op.create_table(
        "crm_campaign_schedules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("crm_campaigns.id"), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("crm_message_templates.id"), nullable=True),
        sa.Column("segment_id", sa.Integer(), sa.ForeignKey("crm_audience_segments.id"), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False, server_default="Africa/Nairobi"),
        sa.Column("recurrence", sa.String(12), nullable=False, server_default="once"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_campaign_id", sa.Integer(), sa.ForeignKey("crm_campaigns.id"), nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="scheduled"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_crm_campaign_schedules_organization_id", "crm_campaign_schedules", ["organization_id"])
    op.create_index("ix_crm_campaign_schedules_campaign_id", "crm_campaign_schedules", ["campaign_id"], unique=True)
    op.create_index("ix_crm_campaign_schedules_next_run_at", "crm_campaign_schedules", ["next_run_at"])
    op.add_column("crm_campaign_schedules", sa.Column("last_error", sa.String(1000), nullable=True))


def downgrade():
    op.drop_column("crm_campaign_schedules", "last_error")
    op.drop_table("crm_campaign_schedules")
    op.drop_table("crm_audience_segments")
    op.drop_table("crm_message_templates")
    op.drop_column("crm_campaign_recipients", "message_snapshot")
    op.drop_column("crm_campaign_recipients", "subject_snapshot")
