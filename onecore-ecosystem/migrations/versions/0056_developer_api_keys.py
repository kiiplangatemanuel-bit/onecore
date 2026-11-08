"""Add scoped developer API credentials and usage audit records."""
from alembic import op
import sqlalchemy as sa

revision = "0056_developer_api_keys"
down_revision = "0055_support_attachments"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "developer_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("key_prefix", sa.String(24), nullable=False, unique=True),
        sa.Column("secret_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("environment", sa.String(16), nullable=False, server_default="sandbox"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_developer_api_keys_organization_id", "developer_api_keys", ["organization_id"])
    op.create_index("ix_developer_api_keys_created_by_user_id", "developer_api_keys", ["created_by_user_id"])

    op.create_table(
        "developer_api_key_usages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("api_key_id", sa.Integer(), sa.ForeignKey("developer_api_keys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint", sa.String(255), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_developer_api_key_usages_api_key_id", "developer_api_key_usages", ["api_key_id"])
    op.create_index("ix_developer_api_key_usages_organization_id", "developer_api_key_usages", ["organization_id"])
    op.create_index("ix_developer_api_key_usages_occurred_at", "developer_api_key_usages", ["occurred_at"])

    if op.get_bind().dialect.name == "postgresql":
        for table in ("developer_api_keys", "developer_api_key_usages"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

        op.execute("""
            CREATE POLICY developer_api_key_select ON developer_api_keys
            FOR SELECT USING (
                secret_hash = NULLIF(current_setting('app.developer_api_key_hash', true), '')
                OR (
                    created_by_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                    AND EXISTS (
                        SELECT 1 FROM memberships m
                        WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.organization_id = developer_api_keys.organization_id
                          AND m.is_active = true AND m.role IN ('org_admin', 'developer')
                    )
                )
                OR EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.organization_id = developer_api_keys.organization_id
                      AND m.is_active = true AND m.role = 'org_admin'
                )
            )
        """)
        op.execute("""
            CREATE POLICY developer_api_key_insert ON developer_api_keys
            FOR INSERT WITH CHECK (
                created_by_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                AND EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.organization_id = developer_api_keys.organization_id
                      AND m.is_active = true AND m.role IN ('org_admin', 'developer')
                )
            )
        """)
        op.execute("""
            CREATE POLICY developer_api_key_update ON developer_api_keys
            FOR UPDATE
            USING (
                (
                    created_by_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                    AND EXISTS (
                        SELECT 1 FROM memberships m
                        WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.organization_id = developer_api_keys.organization_id
                          AND m.is_active = true AND m.role IN ('org_admin', 'developer')
                    )
                )
                OR EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.organization_id = developer_api_keys.organization_id
                      AND m.is_active = true AND m.role = 'org_admin'
                )
            )
            WITH CHECK (
                (
                    created_by_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                    AND EXISTS (
                        SELECT 1 FROM memberships m
                        WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.organization_id = developer_api_keys.organization_id
                          AND m.is_active = true AND m.role IN ('org_admin', 'developer')
                    )
                )
                OR EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.organization_id = developer_api_keys.organization_id
                      AND m.is_active = true AND m.role = 'org_admin'
                )
            )
        """)
        op.execute("""
            CREATE POLICY developer_api_key_usage_select ON developer_api_key_usages
            FOR SELECT USING (
                EXISTS (
                    SELECT 1 FROM developer_api_keys k
                    WHERE k.id = developer_api_key_usages.api_key_id
                      AND (
                          k.created_by_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          OR EXISTS (
                              SELECT 1 FROM memberships m
                              WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                                AND m.organization_id = k.organization_id
                                AND m.is_active = true AND m.role = 'org_admin'
                          )
                      )
                )
            )
        """)
        op.execute("""
            CREATE POLICY developer_api_key_usage_insert ON developer_api_key_usages
            FOR INSERT WITH CHECK (
                EXISTS (
                    SELECT 1 FROM developer_api_keys k
                    WHERE k.id = developer_api_key_usages.api_key_id
                      AND k.organization_id = developer_api_key_usages.organization_id
                      AND (
                          k.secret_hash = NULLIF(current_setting('app.developer_api_key_hash', true), '')
                          OR k.created_by_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      )
                )
            )
        """)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        for policy, table in (
            ("developer_api_key_usage_insert", "developer_api_key_usages"),
            ("developer_api_key_usage_select", "developer_api_key_usages"),
            ("developer_api_key_update", "developer_api_keys"),
            ("developer_api_key_insert", "developer_api_keys"),
            ("developer_api_key_select", "developer_api_keys"),
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        for table in ("developer_api_key_usages", "developer_api_keys"):
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_developer_api_key_usages_occurred_at", table_name="developer_api_key_usages")
    op.drop_index("ix_developer_api_key_usages_organization_id", table_name="developer_api_key_usages")
    op.drop_index("ix_developer_api_key_usages_api_key_id", table_name="developer_api_key_usages")
    op.drop_table("developer_api_key_usages")
    op.drop_index("ix_developer_api_keys_created_by_user_id", table_name="developer_api_keys")
    op.drop_index("ix_developer_api_keys_organization_id", table_name="developer_api_keys")
    op.drop_table("developer_api_keys")
