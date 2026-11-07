"""Hospital inpatient, clinical workflow, billing and integration resources."""
from alembic import op
import sqlalchemy as sa

revision = "0033_healthcare_hospital_operations"
down_revision = "0032_crm_forecast_attribution"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "healthcare_resources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("healthcare_patients.id"), nullable=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("healthcare_resources.id"), nullable=True),
        sa.Column("resource_type", sa.String(40), nullable=False),
        sa.Column("external_key", sa.String(100), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_health_resource_org_type_external", "healthcare_resources",
        ["organization_id", "resource_type", "external_key"], unique=True)
    op.create_index("ix_health_resource_org_type_idem", "healthcare_resources",
        ["organization_id", "resource_type", "idempotency_key"], unique=True)
    op.create_index("ix_health_resource_org_patient_type", "healthcare_resources",
        ["organization_id", "patient_id", "resource_type"])
    op.create_index("ix_healthcare_resources_organization_id", "healthcare_resources", ["organization_id"])
    op.create_index("ix_healthcare_resources_branch_id", "healthcare_resources", ["branch_id"])
    op.create_index("ix_healthcare_resources_patient_id", "healthcare_resources", ["patient_id"])
    op.create_index("ix_healthcare_resources_parent_id", "healthcare_resources", ["parent_id"])
    op.create_index("ix_healthcare_resources_resource_type", "healthcare_resources", ["resource_type"])
    op.create_index("ix_healthcare_resources_status", "healthcare_resources", ["status"])

    op.create_table(
        "healthcare_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("healthcare_patients.id"), nullable=False),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("healthcare_resources.id"), nullable=True),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=True),
        sa.Column("encrypted_detail", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_health_event_org_idempotency", "healthcare_events",
        ["organization_id", "idempotency_key"], unique=True)
    op.create_index("ix_health_event_patient_time", "healthcare_events",
        ["organization_id", "patient_id", "occurred_at"])
    op.create_index("ix_healthcare_events_organization_id", "healthcare_events", ["organization_id"])
    op.create_index("ix_healthcare_events_branch_id", "healthcare_events", ["branch_id"])
    op.create_index("ix_healthcare_events_patient_id", "healthcare_events", ["patient_id"])
    op.create_index("ix_healthcare_events_resource_id", "healthcare_events", ["resource_id"])


def downgrade():
    op.drop_table("healthcare_events")
    op.drop_table("healthcare_resources")
