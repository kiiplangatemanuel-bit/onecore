"""Add encrypted transactional identity email outbox and worker-only updates."""
from alembic import op
import sqlalchemy as sa

revision = "0065_identity_email_outbox"
down_revision = "0064_identity_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "identity_email_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("event_key", sa.String(length=180), nullable=False),
        sa.Column("payload_ciphertext", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "event_key", name="uq_identity_email_user_event"),
        sa.CheckConstraint(
            "purpose IN ('email_verification', 'password_reset')",
            name="ck_identity_email_purpose",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'delivered', 'failed', 'cancelled')",
            name="ck_identity_email_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_identity_email_attempts"),
    )
    op.create_index(
        "ix_identity_email_deliveries_user_id",
        "identity_email_deliveries",
        ["user_id"],
    )
    op.create_index(
        "ix_identity_email_delivery_due",
        "identity_email_deliveries",
        ["status", "next_attempt_at", "updated_at"],
    )
    op.create_index(
        "ix_identity_email_delivery_user_purpose",
        "identity_email_deliveries",
        ["user_id", "purpose", "status"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE public.identity_email_deliveries ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE public.identity_email_deliveries FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY identity_email_owner_select ON public.identity_email_deliveries
            FOR SELECT USING (
                user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                OR current_user = 'onecore_identity_email_worker'
            )
        """)
        op.execute("""
            CREATE POLICY identity_email_owner_insert ON public.identity_email_deliveries
            FOR INSERT WITH CHECK (
                user_id = NULLIF(current_setting('app.user_id', true), '')::integer
            )
        """)
        op.execute("""
            CREATE POLICY identity_email_worker_update ON public.identity_email_deliveries
            FOR UPDATE
            USING (current_user = 'onecore_identity_email_worker')
            WITH CHECK (current_user = 'onecore_identity_email_worker')
        """)
        op.execute("""
            DO $identity_email_grants$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_api') THEN
                    GRANT SELECT, INSERT ON TABLE public.identity_email_deliveries TO onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE public.identity_email_deliveries_id_seq TO onecore_api;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_identity_email_worker') THEN
                    GRANT SELECT, UPDATE ON TABLE public.identity_email_deliveries TO onecore_identity_email_worker;
                END IF;
            END
            $identity_email_grants$
        """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for policy in (
            "identity_email_worker_update",
            "identity_email_owner_insert",
            "identity_email_owner_select",
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON public.identity_email_deliveries")
        op.execute("ALTER TABLE public.identity_email_deliveries NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE public.identity_email_deliveries DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_identity_email_delivery_user_purpose", table_name="identity_email_deliveries")
    op.drop_index("ix_identity_email_delivery_due", table_name="identity_email_deliveries")
    op.drop_index("ix_identity_email_deliveries_user_id", table_name="identity_email_deliveries")
    op.drop_table("identity_email_deliveries")
