"""Enforce tenant isolation for organization-owned domain tables.

The application still performs role/branch checks. This migration adds a database
boundary so a missing organization filter cannot expose another tenant's rows.
Healthcare and identity/authorization tables with specialized semantics are
intentionally excluded and must use dedicated policies.
"""
from alembic import op
import sqlalchemy as sa

revision = "0059_tenant_domain_row_level_security"
down_revision = "0058_support_attachment_scan_evidence"
branch_labels = None
depends_on = None


_SPECIALIZED_TABLES = {
    "memberships",
    "portal_workflow_records",
    "support_tickets",
    "support_messages",
    "support_attachments",
    "developer_api_keys",
    "developer_api_key_usages",
    "developer_webhook_endpoints",
    "developer_webhook_deliveries",
}


def _tenant_tables(bind):
    inspector = sa.inspect(bind)
    selected = []
    for table_name in inspector.get_table_names():
        if table_name in _SPECIALIZED_TABLES or table_name.startswith("healthcare_"):
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "organization_id" in columns:
            selected.append(table_name)
    return sorted(selected)


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    preparer = bind.dialect.identifier_preparer
    user_id = "NULLIF(current_setting('app.user_id', true), '')::integer"
    for table_name in _tenant_tables(bind):
        table = preparer.quote(table_name)
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_scope_access ON {table}
            FOR ALL
            USING (
                (
                    organization_id IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM memberships m
                        WHERE m.organization_id = {table}.organization_id
                          AND m.user_id = {user_id}
                          AND m.is_active = true
                    )
                )
                OR EXISTS (
                    SELECT 1 FROM users u
                    WHERE u.id = {user_id}
                      AND u.is_active = true
                      AND u.platform_role IN ('root_superadmin', 'platform_admin')
                )
            )
            WITH CHECK (
                (
                    organization_id IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM memberships m
                        WHERE m.organization_id = {table}.organization_id
                          AND m.user_id = {user_id}
                          AND m.is_active = true
                    )
                )
                OR EXISTS (
                    SELECT 1 FROM users u
                    WHERE u.id = {user_id}
                      AND u.is_active = true
                      AND u.platform_role IN ('root_superadmin', 'platform_admin')
                )
            )
        """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    preparer = bind.dialect.identifier_preparer
    for table_name in _tenant_tables(bind):
        table = preparer.quote(table_name)
        op.execute(f"DROP POLICY IF EXISTS tenant_scope_access ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
