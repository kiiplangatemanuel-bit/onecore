"""Add tenant-isolated SACCO member register with encrypted KYC metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0066_sacco_membership_kyc"
down_revision = "0065_identity_email_outbox"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "sacco_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("branch_id", sa.String(length=36), sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("member_number", sa.String(length=40), nullable=False),
        sa.Column("full_name", sa.String(length=180), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("identity_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("identity_ciphertext", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending_kyc"),
        sa.Column("review_note", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "member_number", name="uq_sacco_member_org_number"),
        sa.UniqueConstraint("organization_id", "identity_fingerprint", name="uq_sacco_member_org_identity"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_sacco_member_org_idempotency"),
        sa.CheckConstraint("status IN ('pending_kyc', 'active', 'rejected', 'suspended', 'exited')", name="ck_sacco_member_status"),
    )
    op.create_index("ix_sacco_members_organization_id", "sacco_members", ["organization_id"])
    op.create_index("ix_sacco_members_branch_id", "sacco_members", ["branch_id"])
    op.create_index("ix_sacco_member_org_status", "sacco_members", ["organization_id", "status"])
    op.create_index("ix_sacco_member_org_branch_status", "sacco_members", ["organization_id", "branch_id", "status"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE public.sacco_members ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE public.sacco_members FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY sacco_member_tenant_scope ON public.sacco_members
            FOR ALL
            USING (
                organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
                OR EXISTS (
                    SELECT 1 FROM public.memberships m
                    WHERE m.organization_id = sacco_members.organization_id
                      AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.is_active = true
                )
                OR public.onecore_is_platform_admin()
            )
            WITH CHECK (
                organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
                OR EXISTS (
                    SELECT 1 FROM public.memberships m
                    WHERE m.organization_id = sacco_members.organization_id
                      AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.is_active = true
                )
                OR public.onecore_is_platform_admin()
            )
        """)
        op.execute("""
            DO $sacco_grants$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_api') THEN
                    GRANT SELECT, INSERT ON TABLE public.sacco_members TO onecore_api;
                    GRANT UPDATE (status, review_note, reviewed_by, reviewed_at, updated_at)
                        ON TABLE public.sacco_members TO onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE public.sacco_members_id_seq TO onecore_api;
                END IF;
            END
            $sacco_grants$
        """)

def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS sacco_member_tenant_scope ON public.sacco_members")
        op.execute("ALTER TABLE public.sacco_members NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE public.sacco_members DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_sacco_member_org_branch_status", table_name="sacco_members")
    op.drop_index("ix_sacco_member_org_status", table_name="sacco_members")
    op.drop_index("ix_sacco_members_branch_id", table_name="sacco_members")
    op.drop_index("ix_sacco_members_organization_id", table_name="sacco_members")
    op.drop_table("sacco_members")
