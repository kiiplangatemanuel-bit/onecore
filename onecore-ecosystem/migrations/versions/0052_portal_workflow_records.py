"""Add tenant-safe authenticated workflows for independent public portals."""
from alembic import op
import sqlalchemy as sa

revision = "0052_portal_workflow_records"
down_revision = "0051_password_reset_tokens"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "portal_workflow_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("portal_key", sa.String(length=24), nullable=False),
        sa.Column("record_type", sa.String(length=48), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default="private"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_portal_workflow_records_portal_key", "portal_workflow_records", ["portal_key"])
    op.create_index("ix_portal_workflow_records_record_type", "portal_workflow_records", ["record_type"])
    op.create_index("ix_portal_workflow_records_organization_id", "portal_workflow_records", ["organization_id"])
    op.create_index("ix_portal_workflow_records_owner_user_id", "portal_workflow_records", ["owner_user_id"])
    op.create_index("ix_portal_workflow_records_status", "portal_workflow_records", ["status"])
    op.create_index("ix_portal_workflow_org_portal_type", "portal_workflow_records", ["organization_id", "portal_key", "record_type"])
    op.create_index("ix_portal_workflow_owner_portal_type", "portal_workflow_records", ["owner_user_id", "portal_key", "record_type"])
    op.create_index("ix_portal_workflow_public", "portal_workflow_records", ["portal_key", "record_type", "visibility", "status"])


def downgrade():
    op.drop_index("ix_portal_workflow_public", table_name="portal_workflow_records")
    op.drop_index("ix_portal_workflow_owner_portal_type", table_name="portal_workflow_records")
    op.drop_index("ix_portal_workflow_org_portal_type", table_name="portal_workflow_records")
    op.drop_index("ix_portal_workflow_records_status", table_name="portal_workflow_records")
    op.drop_index("ix_portal_workflow_records_owner_user_id", table_name="portal_workflow_records")
    op.drop_index("ix_portal_workflow_records_organization_id", table_name="portal_workflow_records")
    op.drop_index("ix_portal_workflow_records_record_type", table_name="portal_workflow_records")
    op.drop_index("ix_portal_workflow_records_portal_key", table_name="portal_workflow_records")
    op.drop_table("portal_workflow_records")
