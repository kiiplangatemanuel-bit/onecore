"""Add row-level security to Support tickets and messages.

Guest access is bound to a hash of the ticket access token after the API validates
it. Authenticated access is bound to the verified OneCore JWT user context.
"""
from alembic import op

revision = "0053_support_row_level_security"
down_revision = "0052_portal_workflow_records"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return

    for table in ("support_tickets", "support_messages"):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')

    op.execute("""
        CREATE POLICY support_ticket_select ON support_tickets
        FOR SELECT USING (
            (
                created_by_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                AND (
                    organization_id IS NULL OR EXISTS (
                        SELECT 1 FROM memberships m
                        WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.organization_id = support_tickets.organization_id
                          AND m.is_active = true
                    )
                )
            )
            OR (
                organization_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.organization_id = support_tickets.organization_id
                      AND m.is_active = true AND m.role = 'org_admin'
                )
            )
            OR (
                guest_token_hash IS NOT NULL
                AND guest_token_hash = NULLIF(current_setting('app.support_guest_token_hash', true), '')
            )
            OR EXISTS (
                SELECT 1 FROM users u
                WHERE u.id = NULLIF(current_setting('app.user_id', true), '')::integer
                  AND u.is_active = true
                  AND u.platform_role IN ('root_superadmin', 'platform_admin')
            )
        )
    """)
    op.execute("""
        CREATE POLICY support_ticket_insert ON support_tickets
        FOR INSERT WITH CHECK (
            (
                created_by_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                AND (
                    organization_id IS NULL OR EXISTS (
                        SELECT 1 FROM memberships m
                        WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.organization_id = support_tickets.organization_id
                          AND m.is_active = true
                    )
                )
            )
            OR (
                created_by_user_id IS NULL AND organization_id IS NULL
                AND guest_token_hash IS NOT NULL
                AND guest_token_hash = NULLIF(current_setting('app.support_guest_token_hash', true), '')
            )
        )
    """)
    op.execute("""
        CREATE POLICY support_ticket_update ON support_tickets
        FOR UPDATE
        USING (
            (
                created_by_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                AND (
                    organization_id IS NULL OR EXISTS (
                        SELECT 1 FROM memberships m
                        WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.organization_id = support_tickets.organization_id
                          AND m.is_active = true
                    )
                )
            )
            OR (
                organization_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.organization_id = support_tickets.organization_id
                      AND m.is_active = true AND m.role = 'org_admin'
                )
            )
            OR (
                guest_token_hash IS NOT NULL
                AND guest_token_hash = NULLIF(current_setting('app.support_guest_token_hash', true), '')
            )
            OR EXISTS (
                SELECT 1 FROM users u
                WHERE u.id = NULLIF(current_setting('app.user_id', true), '')::integer
                  AND u.is_active = true
                  AND u.platform_role IN ('root_superadmin', 'platform_admin')
            )
        )
        WITH CHECK (
            (
                created_by_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                AND (
                    organization_id IS NULL OR EXISTS (
                        SELECT 1 FROM memberships m
                        WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.organization_id = support_tickets.organization_id
                          AND m.is_active = true
                    )
                )
            )
            OR (
                guest_token_hash IS NOT NULL
                AND guest_token_hash = NULLIF(current_setting('app.support_guest_token_hash', true), '')
            )
            OR EXISTS (
                SELECT 1 FROM users u
                WHERE u.id = NULLIF(current_setting('app.user_id', true), '')::integer
                  AND u.is_active = true
                  AND u.platform_role IN ('root_superadmin', 'platform_admin')
            )
        )
    """)

    op.execute("""
        CREATE POLICY support_message_select ON support_messages
        FOR SELECT USING (
            EXISTS (
                SELECT 1 FROM support_tickets t
                WHERE t.id = support_messages.ticket_id
            )
        )
    """)
    op.execute("""
        CREATE POLICY support_message_insert ON support_messages
        FOR INSERT WITH CHECK (
            EXISTS (
                SELECT 1 FROM support_tickets t
                WHERE t.id = support_messages.ticket_id
                  AND (
                      (
                          author_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND is_staff = false
                          AND (
                              t.organization_id IS NULL
                              OR t.created_by_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                              OR EXISTS (
                                  SELECT 1 FROM memberships m
                                  WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                                    AND m.organization_id = t.organization_id
                                    AND m.is_active = true AND m.role = 'org_admin'
                              )
                          )
                      )
                      OR (
                          author_user_id IS NULL AND is_staff = false
                          AND t.guest_token_hash = NULLIF(current_setting('app.support_guest_token_hash', true), '')
                      )
                      OR (
                          is_staff = true
                          AND EXISTS (
                              SELECT 1 FROM users u
                              WHERE u.id = NULLIF(current_setting('app.user_id', true), '')::integer
                                AND u.is_active = true
                                AND u.platform_role IN ('root_superadmin', 'platform_admin')
                          )
                      )
                  )
            )
        )
    """)


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for policy, table in (
        ("support_message_insert", "support_messages"),
        ("support_message_select", "support_messages"),
        ("support_ticket_update", "support_tickets"),
        ("support_ticket_insert", "support_tickets"),
        ("support_ticket_select", "support_tickets"),
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
    for table in ("support_messages", "support_tickets"):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
