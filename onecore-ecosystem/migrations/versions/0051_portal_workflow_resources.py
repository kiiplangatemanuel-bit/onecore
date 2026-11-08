"""Add tenant- and owner-scoped public portal workflow records."""
from alembic import op
import sqlalchemy as sa

revision = "0051_portal_workflow_resources"
down_revision = "0050_portal_authorization_codes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "portal_resources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("portal", sa.String(24), nullable=False),
        sa.Column("resource_type", sa.String(48), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False, server_default=""),
        sa.Column("data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("visibility", sa.String(12), nullable=False, server_default="private"),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_portal_resources_portal", "portal_resources", ["portal"])
    op.create_index("ix_portal_resources_resource_type", "portal_resources", ["resource_type"])
    op.create_index("ix_portal_resources_organization_id", "portal_resources", ["organization_id"])
    op.create_index("ix_portal_resources_owner_user_id", "portal_resources", ["owner_user_id"])
    op.create_index("ix_portal_resources_visibility", "portal_resources", ["visibility"])
    op.create_index("ix_portal_resources_status", "portal_resources", ["status"])
    op.create_index("ix_portal_resource_public", "portal_resources", ["portal", "resource_type", "visibility", "status"])
    op.create_index("ix_portal_resource_tenant_owner", "portal_resources", ["organization_id", "owner_user_id", "portal"])


def downgrade():
    op.drop_index("ix_portal_resource_tenant_owner", table_name="portal_resources")
    op.drop_index("ix_portal_resource_public", table_name="portal_resources")
    for name in ("ix_portal_resources_status", "ix_portal_resources_visibility",
                 "ix_portal_resources_owner_user_id", "ix_portal_resources_organization_id",
                 "ix_portal_resources_resource_type", "ix_portal_resources_portal"):
        op.drop_index(name, table_name="portal_resources")
    op.drop_table("portal_resources")
