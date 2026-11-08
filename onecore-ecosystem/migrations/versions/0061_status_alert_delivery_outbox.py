"""Create a durable and tenant-safe Status alert email outbox."""
from alembic import op
import sqlalchemy as sa

revision = "0061_status_alert_delivery_outbox"
down_revision = "0060_organization_owner_membership_bootstrap"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "status_alert_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("incident_record_id", sa.Integer(), sa.ForeignKey("portal_workflow_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("event_key", sa.String(length=180), nullable=False),
        sa.Column("subject", sa.String(length=240), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "event_key", name="uq_status_alert_user_event"),
    )
    op.create_index("ix_status_alert_deliveries_user_id", "status_alert_deliveries", ["user_id"])
    op.create_index("ix_status_alert_deliveries_incident_record_id", "status_alert_deliveries", ["incident_record_id"])
    op.create_index("ix_status_alert_deliveries_status", "status_alert_deliveries", ["status"])
    op.create_index("ix_status_alert_deliveries_next_attempt_at", "status_alert_deliveries", ["next_attempt_at"])
    op.execute("ALTER TABLE status_alert_deliveries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE status_alert_deliveries FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY status_alert_delivery_select ON status_alert_deliveries
        FOR SELECT USING (
            user_id = NULLIF(current_setting('app.user_id', true), '')::integer
            OR current_user = 'onecore_status_alert_worker'
        )
    """)
    op.execute("""
        CREATE POLICY status_alert_delivery_insert ON status_alert_deliveries
        FOR INSERT WITH CHECK (
            user_id = NULLIF(current_setting('app.user_id', true), '')::integer
            OR (
                incident_record_id = NULLIF(current_setting('app.status_alert_incident_id', true), '')::integer
                AND public.onecore_is_platform_admin()
            )
            OR current_user = 'onecore_status_alert_worker'
        )
    """)
    op.execute("""
        CREATE POLICY status_alert_delivery_update ON status_alert_deliveries
        FOR UPDATE
        USING (current_user = 'onecore_status_alert_worker')
        WITH CHECK (current_user = 'onecore_status_alert_worker')
    """)


def downgrade():
    op.drop_table("status_alert_deliveries")
