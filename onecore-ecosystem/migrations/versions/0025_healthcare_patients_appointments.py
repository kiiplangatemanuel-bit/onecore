"""Healthcare patient directory and appointment scheduling.

Revision ID: 0025_healthcare_patients_appointments
Revises: 0024_school_fees
"""
from alembic import op
import sqlalchemy as sa

revision = "0025_healthcare_patients_appointments"
down_revision = "0024_school_fees"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "healthcare_patients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("patient_number", sa.String(50), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("emergency_contact_name", sa.String(180), nullable=False, server_default=""),
        sa.Column("emergency_contact_phone", sa.String(32), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_healthcare_patients_organization_id", "healthcare_patients", ["organization_id"])
    op.create_index("ix_healthcare_patients_branch_id", "healthcare_patients", ["branch_id"])
    op.create_index("ix_healthcare_patient_org_number", "healthcare_patients",
                    ["organization_id", "patient_number"], unique=True)

    op.create_table(
        "healthcare_appointments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("healthcare_patients.id"), nullable=False),
        sa.Column("appointment_number", sa.String(60), nullable=False),
        sa.Column("provider_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="scheduled"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_healthcare_appointments_organization_id", "healthcare_appointments", ["organization_id"])
    op.create_index("ix_healthcare_appointments_branch_id", "healthcare_appointments", ["branch_id"])
    op.create_index("ix_healthcare_appointments_patient_id", "healthcare_appointments", ["patient_id"])
    op.create_index("ix_healthcare_appointments_provider_user_id", "healthcare_appointments", ["provider_user_id"])
    op.create_index("ix_healthcare_appointment_org_number", "healthcare_appointments",
                    ["organization_id", "appointment_number"], unique=True)
    op.create_index("ix_healthcare_appointment_provider_start", "healthcare_appointments",
                    ["organization_id", "provider_user_id", "starts_at"])


def downgrade():
    op.drop_table("healthcare_appointments")
    op.drop_table("healthcare_patients")
