"""Add shared public and tenant-scoped portal resources."""
from alembic import op
import sqlalchemy as sa

revision = "0050_shared_portal_access"
down_revision = "0049_verified_org_registration"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "portal_resources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("portal", sa.String(24), nullable=False),
        sa.Column("resource_type", sa.String(48), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="private"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("portal IN ('support','status','developers','docs','community','trust','events','careers','partners')", name="ck_portal_resources_portal"),
        sa.CheckConstraint("visibility IN ('private','organization','public')", name="ck_portal_resources_visibility"),
    )
    op.create_index("ix_portal_resources_portal", "portal_resources", ["portal"])
    op.create_index("ix_portal_resources_resource_type", "portal_resources", ["resource_type"])
    op.create_index("ix_portal_resources_owner_user_id", "portal_resources", ["owner_user_id"])
    op.create_index("ix_portal_resources_organization_id", "portal_resources", ["organization_id"])
    op.create_index("ix_portal_resources_public", "portal_resources", ["portal", "visibility", "status"])
    op.create_index("ix_portal_resources_tenant", "portal_resources", ["portal", "organization_id", "resource_type"])
    op.create_index("ix_portal_resources_owner", "portal_resources", ["portal", "owner_user_id", "resource_type"])

def downgrade():
    op.drop_index("ix_portal_resources_owner", table_name="portal_resources")
    op.drop_index("ix_portal_resources_tenant", table_name="portal_resources")
    op.drop_index("ix_portal_resources_public", table_name="portal_resources")
    op.drop_index("ix_portal_resources_organization_id", table_name="portal_resources")
    op.drop_index("ix_portal_resources_owner_user_id", table_name="portal_resources")
    op.drop_index("ix_portal_resources_resource_type", table_name="portal_resources")
    op.drop_index("ix_portal_resources_portal", table_name="portal_resources")
    op.drop_table("portal_resources")
