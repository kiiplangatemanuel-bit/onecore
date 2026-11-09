"""Add durable account sessions and PKCE portal MFA assurance."""
from alembic import op
import sqlalchemy as sa

revision = "0064_identity_sessions"
down_revision = "0063_fx_statutory_remittances"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("auth_method", sa.String(24), nullable=False),
        sa.Column("mfa_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("device_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("user_agent", sa.String(512), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(120), nullable=False, server_default=""),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_user_created", "user_sessions", ["user_id", "created_at"])
    op.create_index("ix_user_sessions_user_active", "user_sessions", ["user_id", "revoked_at", "expires_at"])

    op.create_table(
        "portal_authorization_assurance",
        sa.Column(
            "portal_code_id", sa.Integer(),
            sa.ForeignKey("portal_authorization_codes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mfa_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_portal_authorization_assurance_user_id", "portal_authorization_assurance", ["user_id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in ("user_sessions", "portal_authorization_assurance"):
            op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
            op.execute(f"""
                CREATE POLICY account_owner_access ON public.{table}
                FOR ALL
                USING (
                    user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                    OR public.onecore_is_platform_admin()
                )
                WITH CHECK (
                    user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                    OR public.onecore_is_platform_admin()
                )
            """)
        op.execute("""
            DO $identity$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_api') THEN
                    GRANT SELECT, INSERT, UPDATE ON TABLE
                        public.user_sessions, public.portal_authorization_assurance
                        TO onecore_api;
                END IF;
            END
            $identity$
        """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in ("portal_authorization_assurance", "user_sessions"):
            op.execute(f"DROP POLICY IF EXISTS account_owner_access ON public.{table}")
            op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("portal_authorization_assurance")
    op.drop_table("user_sessions")
