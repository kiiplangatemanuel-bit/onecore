"""Pharmacy dispensing, clinical safety and advanced laboratory workflows.

Revision ID: 0027_pharmacy_lab_operations
Revises: 0026_pharmacy_lab
"""
from alembic import op
import sqlalchemy as sa

revision = "0027_pharmacy_lab_operations"
down_revision = "0026_pharmacy_lab"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_lab_sample_org_order", table_name="laboratory_samples")
    op.create_index("ix_lab_sample_org_order", "laboratory_samples", ["organization_id", "order_id"], unique=False)
    op.create_table("pharmacy_prescriptions",
        sa.Column("id",sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("patient_id",sa.Integer(),sa.ForeignKey("healthcare_patients.id"),nullable=False),
        sa.Column("encounter_id",sa.Integer(),sa.ForeignKey("healthcare_encounters.id"),nullable=False),
        sa.Column("branch_id",sa.String(36),sa.ForeignKey("branches.id"),nullable=True),
        sa.Column("prescriber_id",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("prescription_number",sa.String(80),nullable=False),
        sa.Column("status",sa.String(20),nullable=False,server_default="active"),
        sa.Column("valid_until",sa.Date(),nullable=False),
        sa.Column("created_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_pharmacy_prescriptions_organization_id","pharmacy_prescriptions",["organization_id"])
    op.create_index("ix_pharmacy_prescriptions_patient_id","pharmacy_prescriptions",["patient_id"])
    op.create_index("ix_pharmacy_prescriptions_encounter_id","pharmacy_prescriptions",["encounter_id"])
    op.create_index("ix_pharmacy_prescriptions_branch_id","pharmacy_prescriptions",["branch_id"])
    op.create_index("ix_pharmacy_rx_org_number","pharmacy_prescriptions",["organization_id","prescription_number"],unique=True)

    op.create_table("pharmacy_prescription_lines",
        sa.Column("id",sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("prescription_id",sa.Integer(),sa.ForeignKey("pharmacy_prescriptions.id"),nullable=False),
        sa.Column("medicine_id",sa.Integer(),sa.ForeignKey("pharmacy_medicines.id"),nullable=False),
        sa.Column("dose",sa.String(120),nullable=False),sa.Column("frequency",sa.String(120),nullable=False),
        sa.Column("duration_days",sa.Integer(),nullable=False),
        sa.Column("quantity_prescribed",sa.Numeric(18,3),nullable=False),
        sa.Column("quantity_dispensed",sa.Numeric(18,3),nullable=False,server_default="0"),
        sa.Column("refills_allowed",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("refills_used",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("status",sa.String(20),nullable=False,server_default="pending"))
    op.create_index("ix_pharmacy_prescription_lines_organization_id","pharmacy_prescription_lines",["organization_id"])
    op.create_index("ix_pharmacy_prescription_lines_prescription_id","pharmacy_prescription_lines",["prescription_id"])
    op.create_index("ix_pharmacy_prescription_lines_medicine_id","pharmacy_prescription_lines",["medicine_id"])

    op.create_table("pharmacy_dispenses",
        sa.Column("id",sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("prescription_line_id",sa.Integer(),sa.ForeignKey("pharmacy_prescription_lines.id"),nullable=False),
        sa.Column("batch_id",sa.Integer(),sa.ForeignKey("pharmacy_batches.id"),nullable=False),
        sa.Column("quantity",sa.Numeric(18,3),nullable=False),sa.Column("unit_price",sa.Numeric(18,2),nullable=False),
        sa.Column("idempotency_key",sa.String(100),nullable=False),
        sa.Column("status",sa.String(20),nullable=False,server_default="dispensed"),
        sa.Column("pharmacist_id",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("verified_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("dispensed_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_pharmacy_dispenses_organization_id","pharmacy_dispenses",["organization_id"])
    op.create_index("ix_pharmacy_dispenses_prescription_line_id","pharmacy_dispenses",["prescription_line_id"])
    op.create_index("ix_pharmacy_dispenses_batch_id","pharmacy_dispenses",["batch_id"])
    op.create_index("ix_pharmacy_dispense_org_key","pharmacy_dispenses",["organization_id","idempotency_key"],unique=True)

    op.create_table("pharmacy_allergies",
        sa.Column("id",sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("patient_id",sa.Integer(),sa.ForeignKey("healthcare_patients.id"),nullable=False),
        sa.Column("allergen",sa.String(180),nullable=False),sa.Column("reaction",sa.String(500),nullable=False,server_default=""),
        sa.Column("severity",sa.String(20),nullable=False,server_default="unknown"),
        sa.Column("status",sa.String(16),nullable=False,server_default="active"),
        sa.Column("recorded_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_pharmacy_allergies_organization_id","pharmacy_allergies",["organization_id"])
    op.create_index("ix_pharmacy_allergies_patient_id","pharmacy_allergies",["patient_id"])

    op.create_table("pharmacy_drug_safety_rules",
        sa.Column("id",sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("medicine_a_id",sa.Integer(),sa.ForeignKey("pharmacy_medicines.id"),nullable=False),
        sa.Column("medicine_b_id",sa.Integer(),sa.ForeignKey("pharmacy_medicines.id"),nullable=True),
        sa.Column("rule_type",sa.String(20),nullable=False),sa.Column("severity",sa.String(20),nullable=False,server_default="warning"),
        sa.Column("description",sa.String(500),nullable=False),sa.Column("is_active",sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column("created_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_pharmacy_drug_safety_rules_organization_id","pharmacy_drug_safety_rules",["organization_id"])
    op.create_index("ix_pharmacy_drug_safety_rules_medicine_a_id","pharmacy_drug_safety_rules",["medicine_a_id"])

    op.create_table("pharmacy_controlled_events",
        sa.Column("id",sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("medicine_id",sa.Integer(),sa.ForeignKey("pharmacy_medicines.id"),nullable=False),
        sa.Column("batch_id",sa.Integer(),sa.ForeignKey("pharmacy_batches.id"),nullable=True),
        sa.Column("prescription_id",sa.Integer(),sa.ForeignKey("pharmacy_prescriptions.id"),nullable=True),
        sa.Column("dispense_id",sa.Integer(),sa.ForeignKey("pharmacy_dispenses.id"),nullable=True),
        sa.Column("event_type",sa.String(40),nullable=False),sa.Column("quantity",sa.Numeric(18,3),nullable=False),
        sa.Column("reason",sa.String(500),nullable=False,server_default=""),
        sa.Column("actor_id",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("witness_id",sa.Integer(),sa.ForeignKey("users.id"),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_pharmacy_controlled_events_organization_id","pharmacy_controlled_events",["organization_id"])
    op.create_index("ix_pharmacy_controlled_events_medicine_id","pharmacy_controlled_events",["medicine_id"])

    op.create_table("pharmacy_lab_workflow_records",
        sa.Column("id",sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("branch_id",sa.String(36),sa.ForeignKey("branches.id"),nullable=True),
        sa.Column("record_type",sa.String(40),nullable=False),
        sa.Column("parent_id",sa.Integer(),nullable=True),
        sa.Column("status",sa.String(24),nullable=False,server_default="pending"),
        sa.Column("idempotency_key",sa.String(120),nullable=True),
        sa.Column("payload",sa.JSON(),nullable=False),
        sa.Column("created_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_pharmacy_lab_workflow_records_organization_id","pharmacy_lab_workflow_records",["organization_id"])
    op.create_index("ix_pharmacy_lab_workflow_records_branch_id","pharmacy_lab_workflow_records",["branch_id"])
    op.create_index("ix_pharmacy_lab_workflow_records_record_type","pharmacy_lab_workflow_records",["record_type"])
    op.create_index("ix_pharmacy_lab_workflow_records_parent_id","pharmacy_lab_workflow_records",["parent_id"])
    op.create_index("ix_pharm_lab_record_org_key","pharmacy_lab_workflow_records",["organization_id","record_type","idempotency_key"],unique=True)

    op.create_table("laboratory_test_panels",
        sa.Column("id",sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("code",sa.String(40),nullable=False),sa.Column("name",sa.String(180),nullable=False),
        sa.Column("description",sa.String(500),nullable=False,server_default=""),
        sa.Column("is_active",sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column("created_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_laboratory_test_panels_organization_id","laboratory_test_panels",["organization_id"])
    op.create_index("ix_lab_panel_org_code","laboratory_test_panels",["organization_id","code"],unique=True)

    op.create_table("laboratory_test_panel_lines",
        sa.Column("id",sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("panel_id",sa.Integer(),sa.ForeignKey("laboratory_test_panels.id"),nullable=False),
        sa.Column("test_id",sa.Integer(),sa.ForeignKey("laboratory_tests.id"),nullable=False))
    op.create_index("ix_laboratory_test_panel_lines_organization_id","laboratory_test_panel_lines",["organization_id"])
    op.create_index("ix_laboratory_test_panel_lines_panel_id","laboratory_test_panel_lines",["panel_id"])
    op.create_index("ix_laboratory_test_panel_lines_test_id","laboratory_test_panel_lines",["test_id"])
    op.create_index("ix_lab_panel_line_unique","laboratory_test_panel_lines",["organization_id","panel_id","test_id"],unique=True)


def downgrade():
    op.drop_index("ix_lab_sample_org_order", table_name="laboratory_samples")
    op.create_index("ix_lab_sample_org_order", "laboratory_samples", ["organization_id", "order_id"], unique=True)
    op.drop_table("laboratory_test_panel_lines")
    op.drop_table("laboratory_test_panels")
    op.drop_table("pharmacy_lab_workflow_records")
    op.drop_table("pharmacy_controlled_events")
    op.drop_table("pharmacy_drug_safety_rules")
    op.drop_table("pharmacy_allergies")
    op.drop_table("pharmacy_dispenses")
    op.drop_table("pharmacy_prescription_lines")
    op.drop_table("pharmacy_prescriptions")
