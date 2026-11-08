"""Add durable, tenant-safe Status incident email alert deliveries."""
from alembic import op
import sqlalchemy as sa

revision = "0060_status_alert_email_outbox"
down_revision = "0059_tenant_domain_row_level_security"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "status_alert_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("incident_record_id", sa.Integer(), sa.ForeignKey("portal_workflow_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("event_key", sa.String(length=180), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "event_key", name="uq_status_alert_user_event"),
    )
    op.create_index("ix_status_alert_due", "status_alert_deliveries", ["status", "next_attempt_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE POLICY status_alert_admin_subscription_read ON portal_workflow_records
            FOR SELECT USING (
                portal_key = 'status'
                AND record_type IN ('alert_subscription', 'notification_preference')
                AND public.onecore_is_platform_admin()
            )
        """)
        op.execute("ALTER TABLE status_alert_deliveries ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE status_alert_deliveries FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY status_alert_delivery_select ON status_alert_deliveries
            FOR SELECT USING (
                user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                OR current_user = 'onecore_status_alert_worker'
                OR public.onecore_is_platform_admin()
            )
        """)
        op.execute("""
            CREATE POLICY status_alert_delivery_insert ON status_alert_deliveries
            FOR INSERT WITH CHECK (public.onecore_is_platform_admin())
        """)
        op.execute("""
            CREATE POLICY status_alert_delivery_worker_update ON status_alert_deliveries
            FOR UPDATE USING (current_user = 'onecore_status_alert_worker')
            WITH CHECK (current_user = 'onecore_status_alert_worker')
        """)
        op.execute("""
            CREATE POLICY status_alert_delivery_worker_delete ON status_alert_deliveries
            FOR DELETE USING (current_user = 'onecore_status_alert_worker')
        """)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS status_alert_admin_subscription_read ON portal_workflow_records")
        for policy in (
            "status_alert_delivery_worker_delete",
            "status_alert_delivery_worker_update",
            "status_alert_delivery_insert",
            "status_alert_delivery_select",
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON status_alert_deliveries")
        op.execute("ALTER TABLE status_alert_deliveries NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE status_alert_deliveries DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_status_alert_due", table_name="status_alert_deliveries")
    op.drop_table("status_alert_deliveries")
