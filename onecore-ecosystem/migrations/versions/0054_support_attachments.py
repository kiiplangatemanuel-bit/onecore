"""Add private support attachment metadata and row-level security."""
from alembic import op
import sqlalchemy as sa

revision = "0054_support_attachments"
down_revision = "0053_support_row_level_security"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "support_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False, unique=True),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_support_attachments_ticket_id", "support_attachments", ["ticket_id"])
    op.create_index("ix_support_attachments_uploaded_by_user_id", "support_attachments", ["uploaded_by_user_id"])
    op.create_index("ix_support_attachments_status", "support_attachments", ["status"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE support_attachments ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE support_attachments FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY support_attachment_select ON support_attachments
            FOR SELECT USING (
                EXISTS (SELECT 1 FROM support_tickets t WHERE t.id = support_attachments.ticket_id)
            )
        """)
        op.execute("""
            CREATE POLICY support_attachment_insert ON support_attachments
            FOR INSERT WITH CHECK (
                uploaded_by_user_id IS NOT DISTINCT FROM
                    NULLIF(current_setting('app.user_id', true), '')::integer
                AND EXISTS (
                    SELECT 1 FROM support_tickets t
                    WHERE t.id = support_attachments.ticket_id
                      AND (
                          t.created_by_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          OR (
                              t.organization_id IS NOT NULL AND EXISTS (
                                  SELECT 1 FROM memberships m
                                  WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                                    AND m.organization_id = t.organization_id
                                    AND m.is_active = true AND m.role = 'org_admin'
                              )
                          )
                      )
                  )
            )
        """)
        op.execute("""
            CREATE POLICY support_attachment_update ON support_attachments
            FOR UPDATE
            USING (
                EXISTS (
                    SELECT 1 FROM support_tickets t
                    WHERE t.id = support_attachments.ticket_id
                      AND (
                          t.created_by_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          OR (
                              t.organization_id IS NOT NULL AND EXISTS (
                                  SELECT 1 FROM memberships m
                                  WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                                    AND m.organization_id = t.organization_id
                                    AND m.is_active = true AND m.role = 'org_admin'
                              )
                          )
                      )
                      OR EXISTS (
                          SELECT 1 FROM users u
                          WHERE u.id = NULLIF(current_setting('app.user_id', true), '')::integer
                            AND u.is_active = true
                            AND u.platform_role IN ('root_superadmin', 'platform_admin')
                      )
                )
            )
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM support_tickets t
                    WHERE t.id = support_attachments.ticket_id
                      AND (
                          t.created_by_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          OR (
                              t.organization_id IS NOT NULL AND EXISTS (
                                  SELECT 1 FROM memberships m
                                  WHERE m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                                    AND m.organization_id = t.organization_id
                                    AND m.is_active = true AND m.role = 'org_admin'
                              )
                          )
                      )
                      OR EXISTS (
                          SELECT 1 FROM users u
                          WHERE u.id = NULLIF(current_setting('app.user_id', true), '')::integer
                            AND u.is_active = true
                            AND u.platform_role IN ('root_superadmin', 'platform_admin')
                      )
                )
            )
        """)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        for policy in ("support_attachment_update", "support_attachment_insert", "support_attachment_select"):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON support_attachments")
        op.execute("ALTER TABLE support_attachments NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE support_attachments DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_support_attachments_status", table_name="support_attachments")
    op.drop_index("ix_support_attachments_uploaded_by_user_id", table_name="support_attachments")
    op.drop_index("ix_support_attachments_ticket_id", table_name="support_attachments")
    op.drop_table("support_attachments")
