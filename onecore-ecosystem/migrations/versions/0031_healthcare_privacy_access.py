"""Healthcare patient identity encryption, grants, consent and access audit.

Revision ID: 0031_healthcare_privacy_access
Revises: 0030_crm_campaign_automation
"""
from alembic import op
import sqlalchemy as sa

revision = "0031_healthcare_privacy_access"
down_revision = "0030_crm_campaign_automation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "healthcare_patients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("patient_number_hash", sa.String(64), nullable=False),
        sa.Column("full_name_encrypted", sa.Text(), nullable=False),
        sa.Column("date_of_birth_encrypted", sa.Text(), nullable=True),
        sa.Column("phone_encrypted", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_health_patient_org_number", "healthcare_patients",
                    ["organization_id", "patient_number_hash"], unique=True)
    op.create_index("ix_healthcare_patients_organization_id", "healthcare_patients", ["organization_id"])
    op.create_index("ix_healthcare_patients_branch_id", "healthcare_patients", ["branch_id"])

    op.create_table(
        "healthcare_access_grants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("healthcare_patients.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("access_level", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("granted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_health_access_grant_active", "healthcare_access_grants",
                    ["organization_id", "patient_id", "user_id", "revoked_at"])
    op.create_index("ix_healthcare_access_grants_organization_id", "healthcare_access_grants", ["organization_id"])
    op.create_index("ix_healthcare_access_grants_patient_id", "healthcare_access_grants", ["patient_id"])
    op.create_index("ix_healthcare_access_grants_user_id", "healthcare_access_grants", ["user_id"])

    op.create_table(
        "healthcare_consents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("healthcare_patients.id"), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(12), nullable=False),
        sa.Column("scope", sa.String(500), nullable=False, server_default=""),
        sa.Column("reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("recorded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_healthcare_consents_organization_id", "healthcare_consents", ["organization_id"])
    op.create_index("ix_healthcare_consents_patient_id", "healthcare_consents", ["patient_id"])

    op.create_table(
        "healthcare_break_glass",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("healthcare_patients.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(1000), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_healthcare_break_glass_organization_id", "healthcare_break_glass", ["organization_id"])
    op.create_index("ix_healthcare_break_glass_patient_id", "healthcare_break_glass", ["patient_id"])
    op.create_index("ix_healthcare_break_glass_user_id", "healthcare_break_glass", ["user_id"])

    op.create_table(
        "healthcare_access_audits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("healthcare_patients.id"), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("access_mode", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_healthcare_access_audits_organization_id", "healthcare_access_audits", ["organization_id"])
    op.create_index("ix_healthcare_access_audits_patient_id", "healthcare_access_audits", ["patient_id"])
    op.create_index("ix_healthcare_access_audits_actor_user_id", "healthcare_access_audits", ["actor_user_id"])


def downgrade():
    op.drop_table("healthcare_access_audits")
    op.drop_table("healthcare_break_glass")
    op.drop_table("healthcare_consents")
    op.drop_table("healthcare_access_grants")
    op.drop_table("healthcare_patients")
