"""Add shared PostgreSQL-backed API rate-limit buckets."""
from alembic import op
import sqlalchemy as sa

revision = "0069_platform_distributed_rate_limits"
down_revision = "0068_sacco_loan_origination"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_rate_limit_buckets",
        sa.Column("key_hash", sa.String(length=64), primary_key=True),
        sa.Column("scope", sa.String(length=40), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("request_count > 0", name="ck_platform_rate_limit_count_positive"),
    )
    op.create_index(
        "ix_platform_rate_limit_buckets_expires_at",
        "platform_rate_limit_buckets",
        ["expires_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE public.platform_rate_limit_buckets ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE public.platform_rate_limit_buckets FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY platform_rate_limit_service
            ON public.platform_rate_limit_buckets
            FOR ALL
            USING (
                current_setting('app.platform_rate_limit_service', true) = 'enabled'
            )
            WITH CHECK (
                current_setting('app.platform_rate_limit_service', true) = 'enabled'
            )
        """)
        op.execute("""
            DO $platform_rate_limit_grants$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_api') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE
                        ON TABLE public.platform_rate_limit_buckets TO onecore_api;
                END IF;
            END
            $platform_rate_limit_grants$
        """)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP POLICY IF EXISTS platform_rate_limit_service "
            "ON public.platform_rate_limit_buckets"
        )
        op.execute(
            "ALTER TABLE public.platform_rate_limit_buckets NO FORCE ROW LEVEL SECURITY"
        )
        op.execute(
            "ALTER TABLE public.platform_rate_limit_buckets DISABLE ROW LEVEL SECURITY"
        )
    op.drop_index(
        "ix_platform_rate_limit_buckets_expires_at",
        table_name="platform_rate_limit_buckets",
    )
    op.drop_table("platform_rate_limit_buckets")
