"""Add subscription billing and tenant-scoped managed document records."""
from alembic import op
import sqlalchemy as sa

revision = "0071_platform_commerce_documents"
down_revision = "0070_sacco_loan_repayments"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("interval", sa.String(16), nullable=False, server_default="monthly"),
        sa.Column("entitlements", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_subscription_plans_code", "subscription_plans", ["code"], unique=True)

    op.create_table(
        "organization_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending_payment"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_organization_subscriptions_organization_id", "organization_subscriptions", ["organization_id"])
    op.create_index("ix_org_subscription_status", "organization_subscriptions", ["organization_id", "status"])

    op.create_table(
        "subscription_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("organization_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("method", sa.String(24), nullable=False),
        sa.Column("external_reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending_verification"),
        sa.Column("verified_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_subscription_payment_org_idempotency"),
    )
    op.create_index("ix_subscription_payments_organization_id", "subscription_payments", ["organization_id"])
    op.create_index("ix_subscription_payments_subscription_id", "subscription_payments", ["subscription_id"])
    op.create_index("ix_subscription_payment_org_status", "subscription_payments", ["organization_id", "status"])

    op.create_table(
        "managed_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("managed_files.id", ondelete="CASCADE"), nullable=True),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False, unique=True),
        sa.Column("content_type", sa.String(160), nullable=False, server_default="application/octet-stream"),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(24), nullable=False, server_default="internal"),
        sa.Column("scan_status", sa.String(24), nullable=False, server_default="clean"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_managed_files_organization_id", "managed_files", ["organization_id"])
    op.create_index("ix_managed_files_parent_id", "managed_files", ["parent_id"])
    op.create_index("ix_managed_file_org_parent", "managed_files", ["organization_id", "parent_id", "deleted_at"])

    op.create_table(
        "managed_file_shares",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", sa.Integer(), sa.ForeignKey("managed_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_downloads", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("downloads", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_managed_file_shares_organization_id", "managed_file_shares", ["organization_id"])
    op.create_index("ix_managed_file_shares_file_id", "managed_file_shares", ["file_id"])
    op.create_index("ix_managed_file_share_file", "managed_file_shares", ["file_id", "revoked_at"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in ("organization_subscriptions", "subscription_payments", "managed_files", "managed_file_shares"):
            op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
            op.execute(f"""
                CREATE POLICY tenant_scope_access ON public.{table}
                FOR ALL
                USING (
                    EXISTS (
                        SELECT 1 FROM public.memberships m
                        WHERE m.organization_id = {table}.organization_id
                          AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.is_active = true
                    )
                    OR {table}.organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
                    OR public.onecore_is_platform_admin()
                    OR (
                        '{table}' = 'managed_file_shares'
                        AND token_hash = NULLIF(current_setting('app.file_share_hash', true), '')
                    )
                )
                WITH CHECK (
                    EXISTS (
                        SELECT 1 FROM public.memberships m
                        WHERE m.organization_id = {table}.organization_id
                          AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.is_active = true
                    )
                    OR {table}.organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
                    OR public.onecore_is_platform_admin()
                )
            """)
        op.execute("""
            CREATE POLICY subscription_plan_read ON public.subscription_plans
            FOR SELECT USING (is_active = true OR public.onecore_is_platform_admin())
        """)
        op.execute("""
            CREATE POLICY subscription_plan_admin_write ON public.subscription_plans
            FOR ALL USING (public.onecore_is_platform_admin())
            WITH CHECK (public.onecore_is_platform_admin())
        """)
        op.execute("""
            DO $platform_commerce$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_api') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
                        public.subscription_plans, public.organization_subscriptions,
                        public.subscription_payments, public.managed_files, public.managed_file_shares
                        TO onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE
                        public.subscription_plans_id_seq, public.organization_subscriptions_id_seq,
                        public.subscription_payments_id_seq, public.managed_files_id_seq,
                        public.managed_file_shares_id_seq TO onecore_api;
                END IF;
            END
            $platform_commerce$
        """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in ("organization_subscriptions", "subscription_payments", "managed_files", "managed_file_shares"):
            op.execute(f"DROP POLICY IF EXISTS tenant_scope_access ON public.{table}")
            op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
        op.execute("DROP POLICY IF EXISTS subscription_plan_admin_write ON public.subscription_plans")
        op.execute("DROP POLICY IF EXISTS subscription_plan_read ON public.subscription_plans")
        op.execute("ALTER TABLE public.subscription_plans NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE public.subscription_plans DISABLE ROW LEVEL SECURITY")
    op.drop_table("managed_file_shares")
    op.drop_table("managed_files")
    op.drop_table("subscription_payments")
    op.drop_table("organization_subscriptions")
    op.drop_table("subscription_plans")
