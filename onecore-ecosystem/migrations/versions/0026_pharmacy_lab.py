"""Pharmacy medicine batches and laboratory order/result workflow.

Revision ID: 0026_pharmacy_lab
Revises: 0025_healthcare_clinic
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_pharmacy_lab"
down_revision = "0025_healthcare_clinic"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pharmacy_medicines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("inventory_product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("sku", sa.String(80), nullable=False),
        sa.Column("generic_name", sa.String(180), nullable=False),
        sa.Column("brand_name", sa.String(180), nullable=False, server_default=""),
        sa.Column("strength", sa.String(80), nullable=False, server_default=""),
        sa.Column("dosage_form", sa.String(60), nullable=False),
        sa.Column("route", sa.String(40), nullable=False, server_default="oral"),
        sa.Column("unit", sa.String(24), nullable=False, server_default="unit"),
        sa.Column("is_controlled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pharmacy_medicines_organization_id", "pharmacy_medicines", ["organization_id"])
    op.create_index("ix_pharmacy_medicine_org_sku", "pharmacy_medicines",
                    ["organization_id", "sku"], unique=True)
    op.create_index("ix_pharmacy_medicine_org_product", "pharmacy_medicines",
                    ["organization_id", "inventory_product_id"], unique=True)

    op.create_table(
        "pharmacy_batches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("medicine_id", sa.Integer(), sa.ForeignKey("pharmacy_medicines.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("batch_number", sa.String(80), nullable=False),
        sa.Column("client_batch_id", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("received_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("remaining_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("selling_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("received_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pharmacy_batches_organization_id", "pharmacy_batches", ["organization_id"])
    op.create_index("ix_pharmacy_batches_medicine_id", "pharmacy_batches", ["medicine_id"])
    op.create_index("ix_pharmacy_batches_branch_id", "pharmacy_batches", ["branch_id"])
    op.create_index("ix_pharmacy_batch_org_client_id", "pharmacy_batches",
                    ["organization_id", "client_batch_id"], unique=True)
    op.create_index("ix_pharmacy_batch_org_medicine_branch_number", "pharmacy_batches",
                    ["organization_id", "medicine_id", "branch_id", "batch_number"], unique=True)
    op.create_index("ix_pharmacy_batch_org_expiry", "pharmacy_batches",
                    ["organization_id", "expiry_date"])

    op.create_table(
        "laboratory_tests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("specimen_type", sa.String(80), nullable=False),
        sa.Column("unit", sa.String(40), nullable=False, server_default=""),
        sa.Column("reference_range", sa.String(180), nullable=False, server_default=""),
        sa.Column("turnaround_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_laboratory_tests_organization_id", "laboratory_tests", ["organization_id"])
    op.create_index("ix_lab_test_org_code", "laboratory_tests",
                    ["organization_id", "code"], unique=True)

    op.create_table(
        "laboratory_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("encounter_id", sa.Integer(), sa.ForeignKey("healthcare_encounters.id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("healthcare_patients.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("ordering_provider_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_order_id", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ordered"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_laboratory_orders_organization_id", "laboratory_orders", ["organization_id"])
    op.create_index("ix_laboratory_orders_encounter_id", "laboratory_orders", ["encounter_id"])
    op.create_index("ix_laboratory_orders_patient_id", "laboratory_orders", ["patient_id"])
    op.create_index("ix_laboratory_orders_branch_id", "laboratory_orders", ["branch_id"])
    op.create_index("ix_lab_order_org_client_id", "laboratory_orders",
                    ["organization_id", "client_order_id"], unique=True)

    op.create_table(
        "laboratory_order_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("laboratory_orders.id"), nullable=False),
        sa.Column("test_id", sa.Integer(), sa.ForeignKey("laboratory_tests.id"), nullable=False),
        sa.Column("test_code", sa.String(40), nullable=False),
        sa.Column("test_name", sa.String(180), nullable=False),
        sa.Column("specimen_type", sa.String(80), nullable=False),
        sa.Column("result_unit", sa.String(40), nullable=False, server_default=""),
        sa.Column("reference_range_snapshot", sa.String(180), nullable=False, server_default=""),
        sa.Column("result_value", sa.Text(), nullable=False, server_default=""),
        sa.Column("result_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("entered_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("validated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_laboratory_order_lines_organization_id", "laboratory_order_lines", ["organization_id"])
    op.create_index("ix_laboratory_order_lines_order_id", "laboratory_order_lines", ["order_id"])
    op.create_index("ix_laboratory_order_lines_test_id", "laboratory_order_lines", ["test_id"])
    op.create_index("ix_lab_order_line_order_test", "laboratory_order_lines",
                    ["organization_id", "order_id", "test_id"], unique=True)

    op.create_table(
        "laboratory_samples",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("laboratory_orders.id"), nullable=False),
        sa.Column("accession_number", sa.String(80), nullable=False),
        sa.Column("specimen_type", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="collected"),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
    )
    op.create_index("ix_laboratory_samples_organization_id", "laboratory_samples", ["organization_id"])
    op.create_index("ix_laboratory_samples_order_id", "laboratory_samples", ["order_id"])
    op.create_index("ix_lab_sample_org_accession", "laboratory_samples",
                    ["organization_id", "accession_number"], unique=True)
    op.create_index("ix_lab_sample_org_order", "laboratory_samples",
                    ["organization_id", "order_id"], unique=True)


def downgrade():
    op.drop_table("laboratory_samples")
    op.drop_table("laboratory_order_lines")
    op.drop_table("laboratory_orders")
    op.drop_table("laboratory_tests")
    op.drop_table("pharmacy_batches")
    op.drop_table("pharmacy_medicines")
