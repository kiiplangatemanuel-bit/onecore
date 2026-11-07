"""Procurement requisition workflow.

Revision ID: 0014_procurement_requisitions
Revises: 0013_school_attendance
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_procurement_requisitions"
down_revision = "0013_school_attendance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "procurement_requisitions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("requisition_number", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("justification", sa.String(1000), nullable=False),
        sa.Column("rejection_reason", sa.String(500), nullable=False),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_requisitions_organization_id", "procurement_requisitions", ["organization_id"])
    op.create_index("ix_procurement_requisitions_branch_id", "procurement_requisitions", ["branch_id"])
    op.create_index("ix_procurement_req_org_number", "procurement_requisitions",
                    ["organization_id", "requisition_number"], unique=True)
    op.create_table(
        "procurement_requisition_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("requisition_id", sa.Integer(), sa.ForeignKey("procurement_requisitions.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("quantity_requested", sa.Numeric(18, 3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_procurement_requisition_lines_organization_id", "procurement_requisition_lines", ["organization_id"])
    op.create_index("ix_procurement_requisition_lines_requisition_id", "procurement_requisition_lines", ["requisition_id"])
    op.create_index("ix_procurement_requisition_lines_product_id", "procurement_requisition_lines", ["product_id"])


def downgrade():
    op.drop_table("procurement_requisition_lines")
    op.drop_table("procurement_requisitions")
