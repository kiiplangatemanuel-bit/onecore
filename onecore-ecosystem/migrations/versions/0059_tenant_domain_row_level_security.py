"""Enforce tenant isolation for organization-owned domain tables."""
from alembic import op
import sqlalchemy as sa

revision = "0059_tenant_domain_row_level_security"
down_revision = "0058_support_attachment_scan_evidence"
branch_labels = None
depends_on = None

_SPECIALIZED_TABLES = {
    "memberships",
    "audit_events",
    "mpesa_payment_intents",
    "mpesa_refund_intents",
    "procurement_settlements",
    "crm_campaign_deliveries",
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
        if table_name in _SPECIALIZED_TABLES:
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "organization_id" in columns:
            selected.append(table_name)
    return sorted(selected)


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Security-definer helpers avoid recursive membership-table RLS when an
    # organization administrator needs to manage members in their own tenant.
    op.execute("""
        CREATE OR REPLACE FUNCTION public.onecore_is_org_admin(target_org_id integer)
        RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT EXISTS (
                SELECT 1 FROM public.memberships m
                WHERE m.organization_id = target_org_id
                  AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                  AND m.is_active = true AND m.role = 'org_admin'
            )
        $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.onecore_is_platform_admin()
        RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT EXISTS (
                SELECT 1 FROM public.users u
                WHERE u.id = NULLIF(current_setting('app.user_id', true), '')::integer
                  AND u.is_active = true
                  AND u.platform_role IN ('root_superadmin', 'platform_admin')
            )
        $$
    """)
    op.execute("GRANT EXECUTE ON FUNCTION public.onecore_is_org_admin(integer) TO PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.onecore_is_platform_admin() TO PUBLIC")

    op.execute("ALTER TABLE memberships ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE memberships FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY membership_select ON memberships
        FOR SELECT USING (
            user_id = NULLIF(current_setting('app.user_id', true), '')::integer
            OR public.onecore_is_org_admin(organization_id)
            OR organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
            OR public.onecore_is_platform_admin()
        )
    """)
    op.execute("""
        CREATE POLICY membership_insert ON memberships
        FOR INSERT WITH CHECK (
            (public.onecore_is_org_admin(organization_id) AND role <> 'org_admin')
            OR public.onecore_is_platform_admin()
        )
    """)
    op.execute("""
        CREATE POLICY membership_update ON memberships
        FOR UPDATE
        USING (public.onecore_is_org_admin(organization_id) OR public.onecore_is_platform_admin())
        WITH CHECK ((public.onecore_is_org_admin(organization_id) AND role <> 'org_admin') OR public.onecore_is_platform_admin())
    """)
    op.execute("""
        CREATE POLICY membership_delete ON memberships
        FOR DELETE USING (
            public.onecore_is_org_admin(organization_id)
            OR public.onecore_is_platform_admin()
        )
    """)

    # Audit logs are append-only and include authenticated and guest Support events.
    op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY audit_event_select ON audit_events
        FOR SELECT USING (
            actor_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
            OR (
                organization_id IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.organization_id = audit_events.organization_id
                      AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.is_active = true
                )
            )
            OR organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
            OR public.onecore_is_platform_admin()
        )
    """)
    op.execute("""
        CREATE POLICY audit_event_insert ON audit_events
        FOR INSERT WITH CHECK (
            (
                actor_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                AND (
                    organization_id IS NULL
                    OR EXISTS (
                        SELECT 1 FROM memberships m
                        WHERE m.organization_id = audit_events.organization_id
                          AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.is_active = true
                    )
                    OR public.onecore_is_platform_admin()
                )
            )
            OR (
                organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
            )
            OR (
                actor_user_id IS NULL AND organization_id IS NULL
                AND NULLIF(current_setting('app.support_guest_token_hash', true), '') IS NOT NULL
            )
        )
    """)

    preparer = bind.dialect.identifier_preparer
    user_id = "NULLIF(current_setting('app.user_id', true), '')::integer"
    organization_id = "NULLIF(current_setting('app.organization_id', true), '')::integer"
    callback_hash = "NULLIF(current_setting('app.provider_callback_token_hash', true), '')"
    for table_name in ("mpesa_payment_intents", "mpesa_refund_intents", "procurement_settlements"):
        if table_name not in sa.inspect(bind).get_table_names():
            continue
        table = preparer.quote(table_name)
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY provider_callback_tenant_scope ON {table}
            FOR ALL
            USING (
                callback_token_hash = {callback_hash}
                OR organization_id = {organization_id}
                OR EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.organization_id = {table}.organization_id
                      AND m.user_id = {user_id} AND m.is_active = true
                )
                OR public.onecore_is_platform_admin()
            )
            WITH CHECK (
                organization_id = {organization_id}
                OR EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.organization_id = {table}.organization_id
                      AND m.user_id = {user_id} AND m.is_active = true
                )
                OR public.onecore_is_platform_admin()
            )
        """)

    if "crm_campaign_deliveries" in sa.inspect(bind).get_table_names():
        table = preparer.quote("crm_campaign_deliveries")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY crm_delivery_tenant_scope ON {table}
            FOR ALL
            USING (
                organization_id = {organization_id}
                OR provider_message_id = NULLIF(current_setting('app.crm_delivery_provider_message_id', true), '')
                OR unsubscribe_token_hash = NULLIF(current_setting('app.crm_unsubscribe_token_hash', true), '')
                OR EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.organization_id = {table}.organization_id
                      AND m.user_id = {user_id} AND m.is_active = true
                )
                OR public.onecore_is_platform_admin()
            )
            WITH CHECK (
                organization_id = {organization_id}
                OR EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.organization_id = {table}.organization_id
                      AND m.user_id = {user_id} AND m.is_active = true
                )
                OR public.onecore_is_platform_admin()
            )
        """)

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
                OR {table}.organization_id = {organization_id}
                OR public.onecore_is_platform_admin()
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
                OR {table}.organization_id = {organization_id}
                OR public.onecore_is_platform_admin()
            )
        """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    preparer = bind.dialect.identifier_preparer
    if "crm_campaign_deliveries" in sa.inspect(bind).get_table_names():
        table = preparer.quote("crm_campaign_deliveries")
        op.execute(f"DROP POLICY IF EXISTS crm_delivery_tenant_scope ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    for table_name in _tenant_tables(bind):
        table = preparer.quote(table_name)
        op.execute(f"DROP POLICY IF EXISTS tenant_scope_access ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    for table_name in ("mpesa_payment_intents", "mpesa_refund_intents", "procurement_settlements"):
        if table_name in sa.inspect(bind).get_table_names():
            table = preparer.quote(table_name)
            op.execute(f"DROP POLICY IF EXISTS provider_callback_tenant_scope ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    for policy in ("audit_event_insert", "audit_event_select"):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON audit_events")
    op.execute("ALTER TABLE audit_events NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events DISABLE ROW LEVEL SECURITY")
    for policy in ("membership_delete", "membership_update", "membership_insert", "membership_select"):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON memberships")
    op.execute("ALTER TABLE memberships NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE memberships DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS public.onecore_is_org_admin(integer)")
    op.execute("DROP FUNCTION IF EXISTS public.onecore_is_platform_admin()")
