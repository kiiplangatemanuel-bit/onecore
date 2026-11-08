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

    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE portal_workflow_records ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE portal_workflow_records FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY portal_workflow_select ON portal_workflow_records
            FOR SELECT USING (
                (visibility = 'public' AND status = 'published' AND organization_id IS NULL)
                OR (
                    owner_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                    AND (
                        organization_id IS NULL
                        OR EXISTS (
                            SELECT 1 FROM memberships m
                            WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                              AND m.organization_id = portal_workflow_records.organization_id
                              AND m.is_active = true
                        )
                    )
                )
                OR (
                    visibility = 'organization' AND organization_id IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM memberships m
                        WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.organization_id = portal_workflow_records.organization_id
                          AND m.is_active = true
                    )
                )
                OR (
                    portal_key = 'trust'
                    AND EXISTS (
                        SELECT 1 FROM users u
                        WHERE u.id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND u.platform_role IN ('root_superadmin', 'security_admin')
                          AND u.is_active = true
                    )
                )
                OR (
                    portal_key = 'careers'
                    AND EXISTS (
                        SELECT 1 FROM users u
                        WHERE u.id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND u.platform_role IN ('root_superadmin', 'recruitment_admin')
                          AND u.is_active = true
                    )
                )
            )
        """)
        op.execute("""
            CREATE POLICY portal_workflow_insert ON portal_workflow_records
            FOR INSERT WITH CHECK (
                (
                    owner_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                    AND (
                        (
                            organization_id IS NULL
                            AND visibility = 'private'
                            AND portal_key IN ('status', 'trust', 'events', 'careers', 'community')
                        )
                        OR (
                            organization_id IS NOT NULL
                            AND visibility IN ('private', 'organization')
                            AND EXISTS (
                                SELECT 1 FROM memberships m
                                WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                                  AND m.organization_id = portal_workflow_records.organization_id
                                  AND m.is_active = true
                                  AND CASE portal_key
                                      WHEN 'developers' THEN m.role IN ('org_admin', 'developer', 'manager')
                                      WHEN 'docs' THEN m.role IN ('org_admin', 'manager', 'school_admin', 'teacher')
                                      WHEN 'community' THEN m.role IN ('org_admin', 'branch_admin', 'manager', 'staff', 'teacher')
                                      WHEN 'events' THEN m.role IN ('org_admin', 'event_manager', 'manager')
                                      WHEN 'partners' THEN m.role IN ('org_admin', 'partner_manager', 'manager')
                                      ELSE m.role IN ('org_admin', 'manager', 'staff')
                                  END
                                  AND (
                                      record_type NOT IN (
                                          'application', 'api_key', 'webhook', 'sandbox_environment',
                                          'organization_guide', 'group', 'attendance', 'partner_profile',
                                          'agreement', 'partner_resource'
                                      )
                                      OR m.role IN ('org_admin', 'manager', 'school_admin', 'partner_manager', 'developer', 'event_manager')
                                  )
                            )
                        )
                    )
                )
                OR (
                    organization_id IS NULL AND visibility = 'public' AND status = 'published'
                    AND (
                        (portal_key = 'status' AND record_type = 'incident')
                        OR (portal_key = 'developers' AND record_type IN ('api_guide', 'example'))
                        OR (portal_key = 'docs' AND record_type = 'guide')
                        OR (portal_key = 'community' AND record_type IN ('announcement', 'public_post'))
                        OR (portal_key = 'trust' AND record_type IN ('security_policy', 'compliance_disclosure'))
                        OR (portal_key = 'events' AND record_type IN ('event', 'announcement'))
                        OR (portal_key = 'careers' AND record_type IN ('vacancy', 'company_information'))
                        OR (portal_key = 'partners' AND record_type IN ('opportunity', 'partner_information'))
                    )
                    AND EXISTS (
                        SELECT 1 FROM users u
                        WHERE u.id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND u.platform_role IN ('root_superadmin', 'platform_admin')
                          AND u.is_active = true
                    )
                )
            )
        """)
        op.execute("""
            CREATE POLICY portal_workflow_update ON portal_workflow_records
            FOR UPDATE
            USING (
                (
                    owner_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                    AND (
                        organization_id IS NULL
                        OR EXISTS (
                            SELECT 1 FROM memberships m
                            WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                              AND m.organization_id = portal_workflow_records.organization_id
                              AND m.is_active = true
                        )
                    )
                )
                OR (
                    portal_key = 'trust'
                    AND EXISTS (
                        SELECT 1 FROM users u
                        WHERE u.id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND u.platform_role IN ('root_superadmin', 'security_admin')
                          AND u.is_active = true
                    )
                )
                OR (
                    portal_key = 'careers'
                    AND EXISTS (
                        SELECT 1 FROM users u
                        WHERE u.id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND u.platform_role IN ('root_superadmin', 'recruitment_admin')
                          AND u.is_active = true
                    )
                )
                OR (
                    visibility = 'organization' AND organization_id IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM memberships m
                        WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.organization_id = portal_workflow_records.organization_id
                          AND m.is_active = true
                          AND CASE portal_key
                              WHEN 'developers' THEN m.role IN ('org_admin', 'manager', 'developer')
                              WHEN 'docs' THEN m.role IN ('org_admin', 'manager', 'school_admin')
                              WHEN 'community' THEN m.role IN ('org_admin', 'manager', 'school_admin', 'partner_manager', 'developer', 'event_manager')
                              WHEN 'events' THEN m.role IN ('org_admin', 'manager', 'event_manager')
                              WHEN 'partners' THEN m.role IN ('org_admin', 'manager', 'partner_manager')
                              ELSE m.role IN ('org_admin', 'manager')
                          END
                    )
                )
            )
            WITH CHECK (
                (
                    owner_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                    AND (
                        organization_id IS NULL
                        OR EXISTS (
                            SELECT 1 FROM memberships m
                            WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                              AND m.organization_id = portal_workflow_records.organization_id
                              AND m.is_active = true
                        )
                    )
                )
                OR (
                    portal_key = 'trust'
                    AND EXISTS (
                        SELECT 1 FROM users u
                        WHERE u.id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND u.platform_role IN ('root_superadmin', 'security_admin')
                          AND u.is_active = true
                    )
                )
                OR (
                    portal_key = 'careers'
                    AND EXISTS (
                        SELECT 1 FROM users u
                        WHERE u.id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND u.platform_role IN ('root_superadmin', 'recruitment_admin')
                          AND u.is_active = true
                    )
                )
                OR (
                    visibility = 'organization' AND organization_id IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM memberships m
                        WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.organization_id = portal_workflow_records.organization_id
                          AND m.is_active = true
                          AND m.role IN ('org_admin', 'manager', 'school_admin', 'partner_manager', 'developer', 'event_manager')
                    )
                )
            )
        """)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS portal_workflow_update ON portal_workflow_records")
        op.execute("DROP POLICY IF EXISTS portal_workflow_insert ON portal_workflow_records")
        op.execute("DROP POLICY IF EXISTS portal_workflow_select ON portal_workflow_records")
        op.execute("ALTER TABLE portal_workflow_records NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE portal_workflow_records DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_portal_workflow_public", table_name="portal_workflow_records")
    op.drop_index("ix_portal_workflow_owner_portal_type", table_name="portal_workflow_records")
    op.drop_index("ix_portal_workflow_org_portal_type", table_name="portal_workflow_records")
    op.drop_index("ix_portal_workflow_records_status", table_name="portal_workflow_records")
    op.drop_index("ix_portal_workflow_records_owner_user_id", table_name="portal_workflow_records")
    op.drop_index("ix_portal_workflow_records_organization_id", table_name="portal_workflow_records")
    op.drop_index("ix_portal_workflow_records_record_type", table_name="portal_workflow_records")
    op.drop_index("ix_portal_workflow_records_portal_key", table_name="portal_workflow_records")
    op.drop_table("portal_workflow_records")
