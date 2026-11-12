"""Add staff-reviewed evidence and activation for SACCO loan disbursement."""
from alembic import op
import sqlalchemy as sa

revision = "0069_sacco_loan_disbursement"
down_revision = "0068_sacco_loan_origination"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sacco_loan_applications") as batch:
        batch.drop_constraint("ck_sacco_loan_application_status", type_="check")
        batch.create_check_constraint(
            "ck_sacco_loan_application_status",
            "status IN ('pending_assessment', 'pending_guarantors', 'pending_approval', "
            "'approved_pending_disbursement', 'active', 'rejected')",
        )
    op.create_table(
        "sacco_loan_disbursements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("channel", sa.String(length=24), nullable=False),
        sa.Column("external_reference", sa.String(length=120), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending_verification"),
        sa.Column("request_note", sa.String(length=500), nullable=False),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "id", name="uq_sacco_loan_disbursement_org_id"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_sacco_loan_disbursement_org_idempotency"),
        sa.ForeignKeyConstraint(
            ["organization_id", "application_id"],
            ["sacco_loan_applications.organization_id", "sacco_loan_applications.id"],
            ondelete="RESTRICT", name="fk_sacco_loan_disbursement_application_tenant",
        ),
        sa.CheckConstraint("amount > 0", name="ck_sacco_loan_disbursement_amount"),
        sa.CheckConstraint("length(currency) = 3", name="ck_sacco_loan_disbursement_currency"),
        sa.CheckConstraint(
            "channel IN ('bank_transfer', 'mpesa', 'cash', 'cheque')",
            name="ck_sacco_loan_disbursement_channel",
        ),
        sa.CheckConstraint(
            "status IN ('pending_verification', 'verified', 'rejected')",
            name="ck_sacco_loan_disbursement_status",
        ),
    )
    op.create_index(
        "ix_sacco_loan_disbursements_organization_id",
        "sacco_loan_disbursements", ["organization_id"],
    )
    op.create_index(
        "ix_sacco_loan_disbursements_application_id",
        "sacco_loan_disbursements", ["application_id"],
    )
    op.create_index(
        "ix_sacco_loan_disbursement_org_created",
        "sacco_loan_disbursements", ["organization_id", "created_at"],
    )
    op.create_index(
        "uq_sacco_loan_disbursement_pending",
        "sacco_loan_disbursements", ["organization_id", "application_id"],
        unique=True, postgresql_where=sa.text("status = 'pending_verification'"),
        sqlite_where=sa.text("status = 'pending_verification'"),
    )
    op.create_index(
        "uq_sacco_loan_disbursement_verified",
        "sacco_loan_disbursements", ["organization_id", "application_id"],
        unique=True, postgresql_where=sa.text("status = 'verified'"),
        sqlite_where=sa.text("status = 'verified'"),
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE public.sacco_loan_disbursements ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE public.sacco_loan_disbursements FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY sacco_loan_disbursement_tenant_scope
            ON public.sacco_loan_disbursements
            FOR ALL
            USING (
                organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
                OR EXISTS (
                    SELECT 1 FROM public.memberships m
                    WHERE m.organization_id = sacco_loan_disbursements.organization_id
                      AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.is_active = true
                )
                OR public.onecore_is_platform_admin()
            )
            WITH CHECK (
                organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
                OR EXISTS (
                    SELECT 1 FROM public.memberships m
                    WHERE m.organization_id = sacco_loan_disbursements.organization_id
                      AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                      AND m.is_active = true
                )
                OR public.onecore_is_platform_admin()
            )
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION public.onecore_guard_sacco_loan_disbursement()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $sacco_loan_disbursement$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'SACCO loan disbursement evidence is retained for audit';
                END IF;
                IF OLD.status <> 'pending_verification' THEN
                    RAISE EXCEPTION 'Reviewed SACCO loan disbursement evidence is immutable';
                END IF;
                IF NEW.status NOT IN ('verified', 'rejected') THEN
                    RAISE EXCEPTION 'Pending disbursement evidence can only be verified or rejected';
                END IF;
                RETURN NEW;
            END
            $sacco_loan_disbursement$
        """)
        op.execute("""
            CREATE TRIGGER trg_sacco_loan_disbursement_guard
            BEFORE UPDATE OR DELETE ON public.sacco_loan_disbursements
            FOR EACH ROW EXECUTE FUNCTION public.onecore_guard_sacco_loan_disbursement()
        """)
        op.execute("""
            DO $sacco_loan_disbursement_grants$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_api') THEN
                    GRANT SELECT, INSERT ON TABLE public.sacco_loan_disbursements TO onecore_api;
                    REVOKE UPDATE, DELETE ON TABLE public.sacco_loan_disbursements FROM onecore_api;
                    GRANT UPDATE (status, reviewed_by, reviewed_at, review_note, updated_at)
                        ON TABLE public.sacco_loan_disbursements TO onecore_api;
                    GRANT UPDATE (status) ON TABLE public.sacco_loan_installments TO onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE public.sacco_loan_disbursements_id_seq TO onecore_api;
                END IF;
            END
            $sacco_loan_disbursement_grants$
        """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_sacco_loan_disbursement_guard ON public.sacco_loan_disbursements")
        op.execute("DROP FUNCTION IF EXISTS public.onecore_guard_sacco_loan_disbursement()")
        op.execute("DROP POLICY IF EXISTS sacco_loan_disbursement_tenant_scope ON public.sacco_loan_disbursements")
        op.execute("ALTER TABLE public.sacco_loan_disbursements NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE public.sacco_loan_disbursements DISABLE ROW LEVEL SECURITY")
        op.execute("""
            DO $sacco_loan_disbursement_revoke$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_api') THEN
                    REVOKE UPDATE (status) ON TABLE public.sacco_loan_installments FROM onecore_api;
                END IF;
            END
            $sacco_loan_disbursement_revoke$
        """)
    op.drop_index("uq_sacco_loan_disbursement_verified", table_name="sacco_loan_disbursements")
    op.drop_index("uq_sacco_loan_disbursement_pending", table_name="sacco_loan_disbursements")
    op.drop_index("ix_sacco_loan_disbursement_org_created", table_name="sacco_loan_disbursements")
    op.drop_index("ix_sacco_loan_disbursements_application_id", table_name="sacco_loan_disbursements")
    op.drop_index("ix_sacco_loan_disbursements_organization_id", table_name="sacco_loan_disbursements")
    op.drop_table("sacco_loan_disbursements")
    with op.batch_alter_table("sacco_loan_applications") as batch:
        batch.drop_constraint("ck_sacco_loan_application_status", type_="check")
        batch.create_check_constraint(
            "ck_sacco_loan_application_status",
            "status IN ('pending_assessment', 'pending_guarantors', 'pending_approval', "
            "'approved_pending_disbursement', 'rejected')",
        )
