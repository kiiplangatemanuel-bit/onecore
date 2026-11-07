"""Healthcare patient privacy, access grants, consent and audit controls.

Revision ID: 0031_healthcare_privacy
Revises: 0030_crm_automation
"""
from alembic import op
import sqlalchemy as sa

revision = "0031_healthcare_privacy"
down_revision = "0030_crm_automation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "healthcare_role_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("assigned_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_healthcare_role_assignments_organization_id", "healthcare_role_assignments", ["organization_id"])
    op.create_index("ix_healthcare_role_assignments_user_id", "healthcare_role_assignments", ["user_id"])
    op.create_index("ix_healthcare_role_assignments_branch_id", "healthcare_role_assignments", ["branch_id"])
    op.create_index("ix_healthcare_role_org_user_branch", "healthcare_role_assignments", ["organization_id", "user_id", "branch_id", "role"], unique=True)

    op.create_table(
        "healthcare_patients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("patient_number", sa.String(40), nullable=False),
        sa.Column("identity_ciphertext", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_healthcare_patients_organization_id", "healthcare_patients", ["organization_id"])
    op.create_index("ix_healthcare_patients_branch_id", "healthcare_patients", ["branch_id"])
    op.create_index("ix_healthcare_patient_org_number", "healthcare_patients", ["organization_id", "patient_number"], unique=True)

    op.create_table(
        "healthcare_patient_access_grants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("healthcare_patients.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_healthcare_patient_access_grants_organization_id", "healthcare_patient_access_grants", ["organization_id"])
    op.create_index("ix_healthcare_patient_access_grants_patient_id", "healthcare_patient_access_grants", ["patient_id"])
    op.create_index("ix_healthcare_patient_access_grants_user_id", "healthcare_patient_access_grants", ["user_id"])

    op.create_table(
        "healthcare_patient_consents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("healthcare_patients.id"), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(12), nullable=False),
        sa.Column("evidence_reference", sa.String(180), nullable=False, server_default=""),
        sa.Column("notes", sa.String(500), nullable=False, server_default=""),
        sa.Column("recorded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_healthcare_patient_consents_organization_id", "healthcare_patient_consents", ["organization_id"])
    op.create_index("ix_healthcare_patient_consents_patient_id", "healthcare_patient_consents", ["patient_id"])

    op.create_table(
        "healthcare_break_glass_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("healthcare_patients.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("justification", sa.String(1000), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_healthcare_break_glass_sessions_organization_id", "healthcare_break_glass_sessions", ["organization_id"])
    op.create_index("ix_healthcare_break_glass_sessions_patient_id", "healthcare_break_glass_sessions", ["patient_id"])
    op.create_index("ix_healthcare_break_glass_sessions_user_id", "healthcare_break_glass_sessions", ["user_id"])

    op.create_table(
        "healthcare_access_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("healthcare_patients.id"), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(80), nullable=False, server_default=""),
        sa.Column("reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("emergency", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_healthcare_access_audit_organization_id", "healthcare_access_audit", ["organization_id"])
    op.create_index("ix_healthcare_access_audit_patient_id", "healthcare_access_audit", ["patient_id"])
    op.create_index("ix_healthcare_access_audit_actor_user_id", "healthcare_access_audit", ["actor_user_id"])

    op.create_table(
        "healthcare_appointments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("healthcare_patients.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("provider_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="scheduled"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_healthcare_appointments_organization_id", "healthcare_appointments", ["organization_id"])
    op.create_index("ix_healthcare_appointments_patient_id", "healthcare_appointments", ["patient_id"])
    op.create_index("ix_healthcare_appointments_branch_id", "healthcare_appointments", ["branch_id"])
    op.create_index("ix_healthcare_appointments_provider_user_id", "healthcare_appointments", ["provider_user_id"])

    op.create_table(
        "healthcare_encounters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("healthcare_patients.id"), nullable=False),
        sa.Column("appointment_id", sa.Integer(), sa.ForeignKey("healthcare_appointments.id"), nullable=True),
        sa.Column("provider_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("clinical_ciphertext", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("signed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_healthcare_encounters_organization_id", "healthcare_encounters", ["organization_id"])
    op.create_index("ix_healthcare_encounters_patient_id", "healthcare_encounters", ["patient_id"])
    op.create_index("ix_healthcare_encounters_appointment_id", "healthcare_encounters", ["appointment_id"])
    op.create_index("ix_healthcare_encounters_provider_user_id", "healthcare_encounters", ["provider_user_id"])


def downgrade():
    op.drop_table("healthcare_encounters")
    op.drop_table("healthcare_appointments")
    op.drop_table("healthcare_access_audit")
    op.drop_table("healthcare_break_glass_sessions")
    op.drop_table("healthcare_patient_consents")
    op.drop_table("healthcare_patient_access_grants")
    op.drop_table("healthcare_patients")
    op.drop_table("healthcare_role_assignments")
