"""Harden CRM automation and healthcare privacy controls.

Revision ID: 0031_crm_healthcare_privacy_hardening
Revises: 0030_crm_healthcare_controls
"""
from alembic import op
import sqlalchemy as sa

revision = "0031_crm_healthcare_privacy_hardening"
down_revision = "0030_crm_healthcare_controls"
branch_labels = None
depends_on = None


def upgrade():
    # CRM template versions and branch scope.
    op.drop_index("ix_crm_template_org_name", table_name="crm_communication_templates")
    op.add_column("crm_communication_templates", sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True))
    op.add_column("crm_communication_templates", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("ix_crm_communication_templates_branch_id", "crm_communication_templates", ["branch_id"])
    op.create_index("ix_crm_template_org_name_version", "crm_communication_templates", ["organization_id", "name", "version"], unique=True)

    # Branch-scoped saved audiences.
    op.add_column("crm_audience_segments", sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True))
    op.create_index("ix_crm_audience_segments_branch_id", "crm_audience_segments", ["branch_id"])

    # Schedule recurrence, audience/template binding and lease recovery.
    op.add_column("crm_campaign_schedules", sa.Column("recurrence", sa.String(12), nullable=False, server_default="once"))
    op.add_column("crm_campaign_schedules", sa.Column("template_id", sa.Integer(), nullable=True))
    op.add_column("crm_campaign_schedules", sa.Column("segment_id", sa.Integer(), nullable=True))
    op.add_column("crm_campaign_schedules", sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("crm_campaign_schedules", sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("crm_campaign_schedules", sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("crm_campaign_schedules", sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("crm_campaign_schedules", sa.Column("last_run_campaign_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("crm_campaign_schedules") as batch:
        batch.create_foreign_key("fk_crm_schedule_template", "crm_communication_templates", ["template_id"], ["id"])
        batch.create_foreign_key("fk_crm_schedule_segment", "crm_audience_segments", ["segment_id"], ["id"])
        batch.create_foreign_key("fk_crm_schedule_last_run_campaign", "crm_campaigns", ["last_run_campaign_id"], ["id"])
    op.create_index("ix_crm_campaign_schedules_next_run_at", "crm_campaign_schedules", ["next_run_at"])
    op.execute("UPDATE crm_campaign_schedules SET next_run_at = scheduled_at WHERE next_run_at IS NULL")

    op.add_column("crm_campaign_recipients", sa.Column("subject_snapshot", sa.String(240), nullable=True))
    op.add_column("crm_campaign_recipients", sa.Column("message_snapshot", sa.Text(), nullable=True))

    # Healthcare access governance and consent evidence.
    op.add_column("healthcare_patient_access", sa.Column("reason", sa.String(500), nullable=False, server_default=""))
    op.add_column("healthcare_consents", sa.Column("evidence_reference", sa.String(180), nullable=False, server_default=""))
    op.add_column("healthcare_consents", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("healthcare_access_audits", sa.Column("emergency", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("healthcare_access_audits") as batch:
        batch.alter_column("action", existing_type=sa.String(32), type_=sa.String(80), existing_nullable=False)

    op.create_table(
        "healthcare_role_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("scope_key", sa.String(36), nullable=False, server_default="*"),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("assigned_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_healthcare_role_assignments_organization_id", "healthcare_role_assignments", ["organization_id"])
    op.create_index("ix_healthcare_role_assignments_user_id", "healthcare_role_assignments", ["user_id"])
    op.create_index("ix_healthcare_role_assignments_branch_id", "healthcare_role_assignments", ["branch_id"])
    op.create_index("ix_healthcare_role_org_user_scope", "healthcare_role_assignments", ["organization_id", "user_id", "scope_key", "role"], unique=True)

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


def downgrade():
    op.drop_table("healthcare_appointments")
    op.drop_index("ix_healthcare_break_glass_sessions_user_id", table_name="healthcare_break_glass_sessions")
    op.drop_index("ix_healthcare_break_glass_sessions_patient_id", table_name="healthcare_break_glass_sessions")
    op.drop_index("ix_healthcare_break_glass_sessions_organization_id", table_name="healthcare_break_glass_sessions")
    op.drop_table("healthcare_break_glass_sessions")
    op.drop_index("ix_healthcare_role_org_user_scope", table_name="healthcare_role_assignments")
    op.drop_index("ix_healthcare_role_assignments_branch_id", table_name="healthcare_role_assignments")
    op.drop_index("ix_healthcare_role_assignments_user_id", table_name="healthcare_role_assignments")
    op.drop_index("ix_healthcare_role_assignments_organization_id", table_name="healthcare_role_assignments")
    op.drop_table("healthcare_role_assignments")

    with op.batch_alter_table("healthcare_access_audits") as batch:
        batch.alter_column("action", existing_type=sa.String(80), type_=sa.String(32), existing_nullable=False)
    op.drop_column("healthcare_access_audits", "emergency")
    op.drop_column("healthcare_consents", "expires_at")
    op.drop_column("healthcare_consents", "evidence_reference")
    op.drop_column("healthcare_patient_access", "reason")

    op.drop_column("crm_campaign_recipients", "message_snapshot")
    op.drop_column("crm_campaign_recipients", "subject_snapshot")

    op.drop_index("ix_crm_campaign_schedules_next_run_at", table_name="crm_campaign_schedules")
    with op.batch_alter_table("crm_campaign_schedules") as batch:
        batch.drop_constraint("fk_crm_schedule_last_run_campaign", type_="foreignkey")
        batch.drop_constraint("fk_crm_schedule_segment", type_="foreignkey")
        batch.drop_constraint("fk_crm_schedule_template", type_="foreignkey")
    op.drop_column("crm_campaign_schedules", "last_run_campaign_id")
    op.drop_column("crm_campaign_schedules", "last_run_at")
    op.drop_column("crm_campaign_schedules", "run_count")
    op.drop_column("crm_campaign_schedules", "lease_until")
    op.drop_column("crm_campaign_schedules", "next_run_at")
    op.drop_column("crm_campaign_schedules", "segment_id")
    op.drop_column("crm_campaign_schedules", "template_id")
    op.drop_column("crm_campaign_schedules", "recurrence")

    op.drop_index("ix_crm_audience_segments_branch_id", table_name="crm_audience_segments")
    with op.batch_alter_table("crm_audience_segments") as batch:
        batch.drop_column("branch_id")
    op.drop_index("ix_crm_template_org_name_version", table_name="crm_communication_templates")
    op.drop_index("ix_crm_communication_templates_branch_id", table_name="crm_communication_templates")
    with op.batch_alter_table("crm_communication_templates") as batch:
        batch.drop_column("version")
        batch.drop_column("branch_id")
    op.create_index("ix_crm_template_org_name", "crm_communication_templates", ["organization_id", "name"], unique=True)
