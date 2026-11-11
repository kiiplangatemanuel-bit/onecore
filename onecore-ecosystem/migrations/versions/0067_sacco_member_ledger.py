"""Add tenant-isolated SACCO savings/share subledger and approval workflow."""
from alembic import op
import sqlalchemy as sa

revision = "0067_sacco_member_ledger"
down_revision = "0066_sacco_membership_kyc"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("uq_sacco_member_org_id", "sacco_members", ["organization_id", "id"], unique=True)
    op.create_table(
        "sacco_financial_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.String(length=36), sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("account_type", sa.String(length=16), nullable=False),
        sa.Column("transaction_type", sa.String(length=24), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="posted"),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "id", name="uq_sacco_financial_org_id"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_sacco_financial_org_idempotency"),
        sa.ForeignKeyConstraint(
            ["organization_id", "member_id"], ["sacco_members.organization_id", "sacco_members.id"],
            ondelete="RESTRICT", name="fk_sacco_financial_member_tenant",
        ),
        sa.CheckConstraint("account_type IN ('savings', 'shares')", name="ck_sacco_financial_account_type"),
        sa.CheckConstraint("transaction_type IN ('deposit', 'withdrawal', 'share_contribution')", name="ck_sacco_financial_transaction_type"),
        sa.CheckConstraint("status IN ('pending_approval', 'posted', 'rejected')", name="ck_sacco_financial_status"),
        sa.CheckConstraint("amount > 0", name="ck_sacco_financial_amount_positive"),
        sa.CheckConstraint(
            "(account_type = 'savings' AND transaction_type IN ('deposit', 'withdrawal')) "
            "OR (account_type = 'shares' AND transaction_type = 'share_contribution')",
            name="ck_sacco_financial_type_account_match",
        ),
    )
    op.create_index("ix_sacco_financial_transactions_organization_id", "sacco_financial_transactions", ["organization_id"])
    op.create_index("ix_sacco_financial_transactions_member_id", "sacco_financial_transactions", ["member_id"])
    op.create_index("ix_sacco_financial_transactions_branch_id", "sacco_financial_transactions", ["branch_id"])
    op.create_index("ix_sacco_financial_org_member_created", "sacco_financial_transactions", ["organization_id", "member_id", "created_at"])
    op.create_index("ix_sacco_financial_org_status", "sacco_financial_transactions", ["organization_id", "status"])

    op.create_table(
        "sacco_ledger_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.String(length=36), sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("account_type", sa.String(length=16), nullable=False),
        sa.Column("signed_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("transaction_id", name="uq_sacco_ledger_transaction"),
        sa.ForeignKeyConstraint(
            ["organization_id", "member_id"], ["sacco_members.organization_id", "sacco_members.id"],
            ondelete="RESTRICT", name="fk_sacco_ledger_member_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "transaction_id"],
            ["sacco_financial_transactions.organization_id", "sacco_financial_transactions.id"],
            ondelete="RESTRICT", name="fk_sacco_ledger_transaction_tenant",
        ),
        sa.CheckConstraint("account_type IN ('savings', 'shares')", name="ck_sacco_ledger_account_type"),
        sa.CheckConstraint("signed_amount <> 0", name="ck_sacco_ledger_nonzero_amount"),
    )
    op.create_index("ix_sacco_ledger_entries_organization_id", "sacco_ledger_entries", ["organization_id"])
    op.create_index("ix_sacco_ledger_entries_member_id", "sacco_ledger_entries", ["member_id"])
    op.create_index("ix_sacco_ledger_entries_branch_id", "sacco_ledger_entries", ["branch_id"])
    op.create_index("ix_sacco_ledger_org_member_account", "sacco_ledger_entries", ["organization_id", "member_id", "account_type", "created_at"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table, policy in (
            ("sacco_financial_transactions", "sacco_financial_transaction_tenant_scope"),
            ("sacco_ledger_entries", "sacco_ledger_entry_tenant_scope"),
        ):
            op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
            op.execute(f"""
                CREATE POLICY {policy} ON public.{table}
                FOR ALL
                USING (
                    organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
                    OR EXISTS (
                        SELECT 1 FROM public.memberships m
                        WHERE m.organization_id = {table}.organization_id
                          AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.is_active = true
                    )
                    OR public.onecore_is_platform_admin()
                )
                WITH CHECK (
                    organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
                    OR EXISTS (
                        SELECT 1 FROM public.memberships m
                        WHERE m.organization_id = {table}.organization_id
                          AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.is_active = true
                    )
                    OR public.onecore_is_platform_admin()
                )
            """)

        op.execute("""
            CREATE OR REPLACE FUNCTION public.onecore_reject_sacco_ledger_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $sacco_ledger$
            BEGIN
                RAISE EXCEPTION 'SACCO ledger entries are immutable; use a compensating transaction';
            END
            $sacco_ledger$
        """)
        op.execute("""
            CREATE TRIGGER trg_sacco_ledger_entries_immutable
            BEFORE UPDATE OR DELETE ON public.sacco_ledger_entries
            FOR EACH ROW EXECUTE FUNCTION public.onecore_reject_sacco_ledger_mutation()
        """)
        op.execute("""
            DO $sacco_finance_grants$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_api') THEN
                    GRANT SELECT, INSERT ON TABLE public.sacco_financial_transactions TO onecore_api;
                    REVOKE UPDATE, DELETE ON TABLE public.sacco_financial_transactions FROM onecore_api;
                    GRANT UPDATE (status, decided_by, decided_at, decision_note, updated_at)
                        ON TABLE public.sacco_financial_transactions TO onecore_api;
                    GRANT SELECT, INSERT ON TABLE public.sacco_ledger_entries TO onecore_api;
                    REVOKE UPDATE, DELETE ON TABLE public.sacco_ledger_entries FROM onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE public.sacco_financial_transactions_id_seq TO onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE public.sacco_ledger_entries_id_seq TO onecore_api;
                END IF;
            END
            $sacco_finance_grants$
        """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_sacco_ledger_entries_immutable ON public.sacco_ledger_entries")
        op.execute("DROP FUNCTION IF EXISTS public.onecore_reject_sacco_ledger_mutation()")
        for table, policy in (
            ("sacco_ledger_entries", "sacco_ledger_entry_tenant_scope"),
            ("sacco_financial_transactions", "sacco_financial_transaction_tenant_scope"),
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table}")
            op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_sacco_ledger_org_member_account", table_name="sacco_ledger_entries")
    op.drop_index("ix_sacco_ledger_entries_branch_id", table_name="sacco_ledger_entries")
    op.drop_index("ix_sacco_ledger_entries_member_id", table_name="sacco_ledger_entries")
    op.drop_index("ix_sacco_ledger_entries_organization_id", table_name="sacco_ledger_entries")
    op.drop_table("sacco_ledger_entries")
    op.drop_index("ix_sacco_financial_org_status", table_name="sacco_financial_transactions")
    op.drop_index("ix_sacco_financial_org_member_created", table_name="sacco_financial_transactions")
    op.drop_index("ix_sacco_financial_transactions_branch_id", table_name="sacco_financial_transactions")
    op.drop_index("ix_sacco_financial_transactions_member_id", table_name="sacco_financial_transactions")
    op.drop_index("ix_sacco_financial_transactions_organization_id", table_name="sacco_financial_transactions")
    op.drop_table("sacco_financial_transactions")
    op.drop_index("uq_sacco_member_org_id", table_name="sacco_members")
