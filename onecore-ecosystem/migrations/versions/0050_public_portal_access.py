"""Add public portal content and tenant-scoped portal resources."""
from alembic import op
import sqlalchemy as sa

revision = "0050_public_portal_access"
down_revision = "0049_verified_org_registration"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "portal_public_content",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("portal_key", sa.String(32), nullable=False),
        sa.Column("content_type", sa.String(48), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_portal_public_content_portal_key", "portal_public_content", ["portal_key"])
    op.create_index("ix_portal_public_content_content_type", "portal_public_content", ["content_type"])
    op.create_index("ix_portal_public_content_status", "portal_public_content", ["status"])
    op.create_index("uq_portal_public_content_slug", "portal_public_content", ["portal_key", "slug"], unique=True)
    op.create_table(
        "portal_resources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("portal_key", sa.String(32), nullable=False),
        sa.Column("resource_kind", sa.String(48), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="private"),
        sa.Column("data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_portal_resources_portal_key", "portal_resources", ["portal_key"])
    op.create_index("ix_portal_resources_resource_kind", "portal_resources", ["resource_kind"])
    op.create_index("ix_portal_resources_organization_id", "portal_resources", ["organization_id"])
    op.create_index("ix_portal_resources_owner_user_id", "portal_resources", ["owner_user_id"])
    op.create_index("ix_portal_resource_owner", "portal_resources", ["portal_key", "owner_user_id", "resource_kind"])
    op.create_index("ix_portal_resource_org", "portal_resources", ["portal_key", "organization_id", "resource_kind", "visibility"])


def downgrade():
    op.drop_index("ix_portal_resource_org", table_name="portal_resources")
    op.drop_index("ix_portal_resource_owner", table_name="portal_resources")
    op.drop_index("ix_portal_resources_owner_user_id", table_name="portal_resources")
    op.drop_index("ix_portal_resources_organization_id", table_name="portal_resources")
    op.drop_index("ix_portal_resources_resource_kind", table_name="portal_resources")
    op.drop_index("ix_portal_resources_portal_key", table_name="portal_resources")
    op.drop_table("portal_resources")
    op.drop_index("uq_portal_public_content_slug", table_name="portal_public_content")
    op.drop_index("ix_portal_public_content_status", table_name="portal_public_content")
    op.drop_index("ix_portal_public_content_content_type", table_name="portal_public_content")
    op.drop_index("ix_portal_public_content_portal_key", table_name="portal_public_content")
    op.drop_table("portal_public_content")
