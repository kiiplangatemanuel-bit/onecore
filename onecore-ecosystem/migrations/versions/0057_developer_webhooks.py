"""Add durable signed developer webhook endpoints and delivery outbox."""
from alembic import op
import sqlalchemy as sa

revision = "0057_developer_webhooks"
down_revision = "0056_developer_api_keys"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "developer_webhook_endpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_record_id", sa.Integer(), sa.ForeignKey("portal_workflow_records.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_developer_webhook_endpoints_workflow_record_id", "developer_webhook_endpoints", ["workflow_record_id"], unique=True)
    op.create_index("ix_developer_webhook_endpoints_organization_id", "developer_webhook_endpoints", ["organization_id"])

    op.create_table(
        "developer_webhook_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("endpoint_id", sa.Integer(), sa.ForeignKey("developer_webhook_endpoints.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(80), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("endpoint_id", "event_id", name="uq_developer_webhook_endpoint_event"),
    )
    op.create_index("ix_developer_webhook_deliveries_endpoint_id", "developer_webhook_deliveries", ["endpoint_id"])
    op.create_index("ix_developer_webhook_deliveries_organization_id", "developer_webhook_deliveries", ["organization_id"])
    op.create_index("ix_developer_webhook_deliveries_event_type", "developer_webhook_deliveries", ["event_type"])
    op.create_index("ix_developer_webhook_deliveries_status", "developer_webhook_deliveries", ["status"])
    op.create_index("ix_developer_webhook_deliveries_next_attempt_at", "developer_webhook_deliveries", ["next_attempt_at"])

    if op.get_bind().dialect.name == "postgresql":
        for table in ("developer_webhook_endpoints", "developer_webhook_deliveries"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY developer_webhook_endpoint_select ON developer_webhook_endpoints
            FOR SELECT USING (
                current_setting('app.webhook_worker', true) = 'true'
                OR EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.organization_id = developer_webhook_endpoints.organization_id
                      AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.is_active = true AND m.role IN ('org_admin', 'developer')
                )
            )
        """)
        op.execute("""
            CREATE POLICY developer_webhook_endpoint_insert ON developer_webhook_endpoints
            FOR INSERT WITH CHECK (
                current_setting('app.webhook_worker', true) = 'true'
                OR EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.organization_id = developer_webhook_endpoints.organization_id
                      AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.is_active = true AND m.role IN ('org_admin', 'developer')
                )
            )
        """)
        op.execute("""
            CREATE POLICY developer_webhook_endpoint_update ON developer_webhook_endpoints
            FOR UPDATE USING (
                current_setting('app.webhook_worker', true) = 'true'
                OR EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.organization_id = developer_webhook_endpoints.organization_id
                      AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.is_active = true AND m.role IN ('org_admin', 'developer')
                )
            ) WITH CHECK (
                current_setting('app.webhook_worker', true) = 'true'
                OR EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.organization_id = developer_webhook_endpoints.organization_id
                      AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.is_active = true AND m.role IN ('org_admin', 'developer')
                )
            )
        """)
        op.execute("""
            CREATE POLICY developer_webhook_delivery_select ON developer_webhook_deliveries
            FOR SELECT USING (
                current_setting('app.webhook_worker', true) = 'true'
                OR EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.organization_id = developer_webhook_deliveries.organization_id
                      AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.is_active = true AND m.role IN ('org_admin', 'developer')
                )
            )
        """)
        op.execute("""
            CREATE POLICY developer_webhook_delivery_insert ON developer_webhook_deliveries
            FOR INSERT WITH CHECK (
                current_setting('app.webhook_worker', true) = 'true'
                OR EXISTS (
                    SELECT 1 FROM memberships m
                    WHERE m.organization_id = developer_webhook_deliveries.organization_id
                      AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.is_active = true AND m.role IN ('org_admin', 'developer')
                )
            )
        """)
        op.execute("""
            CREATE POLICY developer_webhook_delivery_update ON developer_webhook_deliveries
            FOR UPDATE USING (
                current_setting('app.webhook_worker', true) = 'true'
            ) WITH CHECK (
                current_setting('app.webhook_worker', true) = 'true'
            )
        """)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        for policy, table in (
            ("developer_webhook_delivery_update", "developer_webhook_deliveries"),
            ("developer_webhook_delivery_insert", "developer_webhook_deliveries"),
            ("developer_webhook_delivery_select", "developer_webhook_deliveries"),
            ("developer_webhook_endpoint_update", "developer_webhook_endpoints"),
            ("developer_webhook_endpoint_insert", "developer_webhook_endpoints"),
            ("developer_webhook_endpoint_select", "developer_webhook_endpoints"),
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        for table in ("developer_webhook_deliveries", "developer_webhook_endpoints"):
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_developer_webhook_deliveries_next_attempt_at", table_name="developer_webhook_deliveries")
    op.drop_index("ix_developer_webhook_deliveries_status", table_name="developer_webhook_deliveries")
    op.drop_index("ix_developer_webhook_deliveries_event_type", table_name="developer_webhook_deliveries")
    op.drop_index("ix_developer_webhook_deliveries_organization_id", table_name="developer_webhook_deliveries")
    op.drop_index("ix_developer_webhook_deliveries_endpoint_id", table_name="developer_webhook_deliveries")
    op.drop_table("developer_webhook_deliveries")
    op.drop_index("ix_developer_webhook_endpoints_organization_id", table_name="developer_webhook_endpoints")
    op.drop_index("ix_developer_webhook_endpoints_workflow_record_id", table_name="developer_webhook_endpoints")
    op.drop_table("developer_webhook_endpoints")
