"""Add immutable version history for tenant-managed documents."""
from alembic import op
import sqlalchemy as sa

revision = "0072_managed_file_versions"
down_revision = "0071_platform_commerce_documents"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "managed_file_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", sa.Integer(), sa.ForeignKey("managed_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False, unique=True),
        sa.Column("content_type", sa.String(160), nullable=False, server_default="application/octet-stream"),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("scan_status", sa.String(24), nullable=False, server_default="clean"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("file_id", "version_number", name="uq_managed_file_version_number"),
    )
    op.create_index("ix_managed_file_versions_organization_id", "managed_file_versions", ["organization_id"])
    op.create_index("ix_managed_file_versions_file_id", "managed_file_versions", ["file_id"])
    op.create_index("ix_managed_file_version_org_file", "managed_file_versions", ["organization_id", "file_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE public.managed_file_versions ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE public.managed_file_versions FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY tenant_scope_access ON public.managed_file_versions
            FOR ALL
            USING (
                EXISTS (
                    SELECT 1 FROM public.memberships m
                    WHERE m.organization_id = managed_file_versions.organization_id
                      AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.is_active = true
                )
                OR managed_file_versions.organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
                OR public.onecore_is_platform_admin()
            )
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM public.memberships m
                    WHERE m.organization_id = managed_file_versions.organization_id
                      AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.is_active = true
                )
                OR managed_file_versions.organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
                OR public.onecore_is_platform_admin()
            )
        """)
        op.execute("""
            DO $file_versions$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_api') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.managed_file_versions TO onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE public.managed_file_versions_id_seq TO onecore_api;
                END IF;
            END
            $file_versions$
        """)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_scope_access ON public.managed_file_versions")
        op.execute("ALTER TABLE public.managed_file_versions NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE public.managed_file_versions DISABLE ROW LEVEL SECURITY")
    op.drop_table("managed_file_versions")
