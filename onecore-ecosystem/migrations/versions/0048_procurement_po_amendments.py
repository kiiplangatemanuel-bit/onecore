"""Versioned purchase-order amendments and approval-version isolation."""
from alembic import op
import sqlalchemy as sa

revision = "0048_procurement_po_amendments"
down_revision = "0047_pos_loyalty_redemption_policy"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("procurement_purchase_orders", sa.Column("amendment_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("procurement_approval_actions", sa.Column("approval_version", sa.Integer(), nullable=False, server_default="1"))
    op.drop_index("ix_procurement_approval_action_org_entity_level", table_name="procurement_approval_actions")
    op.create_index("ix_procurement_approval_action_org_entity_level", "procurement_approval_actions", ["organization_id", "entity_type", "entity_id", "approval_level", "approval_version"], unique=True)
    op.create_table("procurement_purchase_order_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("procurement_purchase_orders.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("change_reason", sa.String(500), nullable=False),
        sa.Column("supporting_notes", sa.String(2000), nullable=False, server_default=""),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "purchase_order_id", "version_number", name="uq_procurement_po_version"))
    op.create_index("ix_procurement_purchase_order_versions_organization_id", "procurement_purchase_order_versions", ["organization_id"])
    op.create_index("ix_procurement_purchase_order_versions_purchase_order_id", "procurement_purchase_order_versions", ["purchase_order_id"])


def downgrade():
    op.drop_index("ix_procurement_purchase_order_versions_purchase_order_id", table_name="procurement_purchase_order_versions")
    op.drop_index("ix_procurement_purchase_order_versions_organization_id", table_name="procurement_purchase_order_versions")
    op.drop_table("procurement_purchase_order_versions")
    op.drop_index("ix_procurement_approval_action_org_entity_level", table_name="procurement_approval_actions")
    op.create_index("ix_procurement_approval_action_org_entity_level", "procurement_approval_actions", ["organization_id", "entity_type", "entity_id", "approval_level"], unique=True)
    with op.batch_alter_table("procurement_approval_actions") as batch:
        batch.drop_column("approval_version")
    with op.batch_alter_table("procurement_purchase_orders") as batch:
        batch.drop_column("amendment_version")
