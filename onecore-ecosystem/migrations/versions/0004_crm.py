"""Tenant-scoped CRM contacts, pipeline leads and activities.

Revision ID: 0004_crm
Revises: 0003_accounting
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_crm"
down_revision = "0003_accounting"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "crm_contacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("full_name", sa.String(180), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("company", sa.String(180), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_crm_contacts_organization_id", "crm_contacts", ["organization_id"])
    op.create_index("ix_crm_contacts_branch_id", "crm_contacts", ["branch_id"])
    op.create_index("ix_crm_contact_org_email", "crm_contacts", ["organization_id", "email"])
    op.create_index("ix_crm_contact_org_phone", "crm_contacts", ["organization_id", "phone"])

    op.create_table(
        "crm_leads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id"), nullable=True),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("source", sa.String(60), nullable=False),
        sa.Column("stage", sa.String(24), nullable=False),
        sa.Column("estimated_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("assigned_to", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("next_step", sa.String(500), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_crm_leads_organization_id", "crm_leads", ["organization_id"])
    op.create_index("ix_crm_leads_branch_id", "crm_leads", ["branch_id"])
    op.create_index("ix_crm_leads_contact_id", "crm_leads", ["contact_id"])
    op.create_index("ix_crm_lead_org_stage", "crm_leads", ["organization_id", "stage"])

    op.create_table(
        "crm_activities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id"), nullable=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("crm_leads.id"), nullable=True),
        sa.Column("activity_type", sa.String(24), nullable=False),
        sa.Column("subject", sa.String(180), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_crm_activities_organization_id", "crm_activities", ["organization_id"])
    op.create_index("ix_crm_activities_contact_id", "crm_activities", ["contact_id"])
    op.create_index("ix_crm_activities_lead_id", "crm_activities", ["lead_id"])


def downgrade():
    op.drop_table("crm_activities")
    op.drop_table("crm_leads")
    op.drop_table("crm_contacts")
