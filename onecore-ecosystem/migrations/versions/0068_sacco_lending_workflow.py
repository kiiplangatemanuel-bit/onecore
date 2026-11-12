"""Add tenant-isolated SACCO loan products, underwriting and immutable loan ledger."""
from alembic import op
import sqlalchemy as sa

revision = "0068_sacco_lending_workflow"
down_revision = "0067_sacco_member_ledger"
branch_labels = None
depends_on = None


def _tenant_policy(table: str, policy: str) -> None:
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


def upgrade():
    op.create_table(
        "sacco_loan_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("min_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("max_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("annual_interest_rate", sa.Numeric(7, 4), nullable=False),
        sa.Column("min_term_months", sa.Integer(), nullable=False),
        sa.Column("max_term_months", sa.Integer(), nullable=False),
        sa.Column("max_debt_service_ratio", sa.Numeric(5, 4), nullable=False, server_default="0.4000"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "code", name="uq_sacco_loan_product_org_code"),
        sa.UniqueConstraint("organization_id", "id", name="uq_sacco_loan_product_org_id"),
        sa.CheckConstraint("min_amount > 0 AND max_amount >= min_amount", name="ck_sacco_loan_product_amount_range"),
        sa.CheckConstraint("annual_interest_rate >= 0 AND annual_interest_rate <= 100", name="ck_sacco_loan_product_rate"),
        sa.CheckConstraint("min_term_months >= 1 AND max_term_months >= min_term_months AND max_term_months <= 120", name="ck_sacco_loan_product_term_range"),
        sa.CheckConstraint("max_debt_service_ratio > 0 AND max_debt_service_ratio <= 1", name="ck_sacco_loan_product_dsr"),
    )
    op.create_index("ix_sacco_loan_products_organization_id", "sacco_loan_products", ["organization_id"])
    op.create_index("ix_sacco_loan_product_org_active", "sacco_loan_products", ["organization_id", "is_active"])

    op.create_table(
        "sacco_loan_applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("requested_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=False),
        sa.Column("annual_interest_rate", sa.Numeric(7, 4), nullable=False),
        sa.Column("max_debt_service_ratio", sa.Numeric(5, 4), nullable=False),
        sa.Column("purpose", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="submitted"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("assessment_monthly_net_income", sa.Numeric(18, 2), nullable=True),
        sa.Column("assessment_existing_monthly_debt", sa.Numeric(18, 2), nullable=True),
        sa.Column("assessment_monthly_installment", sa.Numeric(18, 2), nullable=True),
        sa.Column("assessment_total_interest", sa.Numeric(18, 2), nullable=True),
        sa.Column("assessment_debt_service_ratio", sa.Numeric(7, 4), nullable=True),
        sa.Column("assessment_recommendation", sa.String(10), nullable=True),
        sa.Column("assessment_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("assessed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("disbursed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("disbursed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "id", name="uq_sacco_loan_application_org_id"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_sacco_loan_application_org_idempotency"),
        sa.ForeignKeyConstraint(
            ["organization_id", "member_id"], ["sacco_members.organization_id", "sacco_members.id"],
            ondelete="RESTRICT", name="fk_sacco_loan_application_member_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "product_id"], ["sacco_loan_products.organization_id", "sacco_loan_products.id"],
            ondelete="RESTRICT", name="fk_sacco_loan_application_product_tenant",
        ),
        sa.CheckConstraint("requested_amount > 0", name="ck_sacco_loan_application_amount"),
        sa.CheckConstraint("term_months BETWEEN 1 AND 120", name="ck_sacco_loan_application_term"),
        sa.CheckConstraint("annual_interest_rate >= 0 AND annual_interest_rate <= 100", name="ck_sacco_loan_application_rate"),
        sa.CheckConstraint("max_debt_service_ratio > 0 AND max_debt_service_ratio <= 1", name="ck_sacco_loan_application_dsr_limit"),
        sa.CheckConstraint("status IN ('submitted', 'assessed', 'approved', 'rejected', 'disbursed', 'closed')", name="ck_sacco_loan_application_status"),
        sa.CheckConstraint("assessment_recommendation IS NULL OR assessment_recommendation IN ('approve', 'decline')", name="ck_sacco_loan_application_recommendation"),
    )
    op.create_index("ix_sacco_loan_applications_organization_id", "sacco_loan_applications", ["organization_id"])
    op.create_index("ix_sacco_loan_applications_member_id", "sacco_loan_applications", ["member_id"])
    op.create_index("ix_sacco_loan_applications_product_id", "sacco_loan_applications", ["product_id"])
    op.create_index("ix_sacco_loan_applications_branch_id", "sacco_loan_applications", ["branch_id"])
    op.create_index("ix_sacco_loan_application_org_member_created", "sacco_loan_applications", ["organization_id", "member_id", "created_at"])
    op.create_index("ix_sacco_loan_application_org_status", "sacco_loan_applications", ["organization_id", "status"])
    op.create_index("ix_sacco_loan_application_org_branch_status", "sacco_loan_applications", ["organization_id", "branch_id", "status"])

    op.create_table(
        "sacco_loan_ledger_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("loan_application_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entry_type", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("principal_delta", sa.Numeric(18, 2), nullable=False),
        sa.Column("interest_delta", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_sacco_loan_ledger_org_idempotency"),
        sa.ForeignKeyConstraint(
            ["organization_id", "loan_application_id"],
            ["sacco_loan_applications.organization_id", "sacco_loan_applications.id"],
            ondelete="RESTRICT", name="fk_sacco_loan_ledger_application_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "member_id"], ["sacco_members.organization_id", "sacco_members.id"],
            ondelete="RESTRICT", name="fk_sacco_loan_ledger_member_tenant",
        ),
        sa.CheckConstraint("entry_type IN ('disbursement', 'repayment')", name="ck_sacco_loan_ledger_entry_type"),
        sa.CheckConstraint("amount > 0", name="ck_sacco_loan_ledger_amount"),
        sa.CheckConstraint(
            "(entry_type = 'disbursement' AND principal_delta = amount AND interest_delta >= 0) OR "
            "(entry_type = 'repayment' AND principal_delta <= 0 AND interest_delta <= 0 AND principal_delta + interest_delta = -amount)",
            name="ck_sacco_loan_ledger_allocation",
        ),
    )
    op.create_index("ix_sacco_loan_ledger_entries_organization_id", "sacco_loan_ledger_entries", ["organization_id"])
    op.create_index("ix_sacco_loan_ledger_entries_loan_application_id", "sacco_loan_ledger_entries", ["loan_application_id"])
    op.create_index("ix_sacco_loan_ledger_entries_member_id", "sacco_loan_ledger_entries", ["member_id"])
    op.create_index("ix_sacco_loan_ledger_entries_branch_id", "sacco_loan_ledger_entries", ["branch_id"])
    op.create_index("ix_sacco_loan_ledger_org_application_created", "sacco_loan_ledger_entries", ["organization_id", "loan_application_id", "created_at"])
    op.create_index(
        "uq_sacco_loan_one_disbursement", "sacco_loan_ledger_entries", ["loan_application_id"],
        unique=True, postgresql_where=sa.text("entry_type = 'disbursement'"),
        sqlite_where=sa.text("entry_type = 'disbursement'"),
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table, policy in (
            ("sacco_loan_products", "sacco_loan_product_tenant_scope"),
            ("sacco_loan_applications", "sacco_loan_application_tenant_scope"),
            ("sacco_loan_ledger_entries", "sacco_loan_ledger_entry_tenant_scope"),
        ):
            _tenant_policy(table, policy)

        op.execute("""
            CREATE OR REPLACE FUNCTION public.onecore_reject_sacco_loan_ledger_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $sacco_loan_ledger$
            BEGIN
                RAISE EXCEPTION 'SACCO loan ledger entries are immutable; use a compensating workflow';
            END
            $sacco_loan_ledger$
        """)
        op.execute("""
            CREATE TRIGGER trg_sacco_loan_ledger_entries_immutable
            BEFORE UPDATE OR DELETE ON public.sacco_loan_ledger_entries
            FOR EACH ROW EXECUTE FUNCTION public.onecore_reject_sacco_loan_ledger_mutation()
        """)
        op.execute("""
            DO $sacco_loan_grants$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_api') THEN
                    GRANT SELECT, INSERT ON TABLE public.sacco_loan_products TO onecore_api;
                    REVOKE UPDATE, DELETE ON TABLE public.sacco_loan_products FROM onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE public.sacco_loan_products_id_seq TO onecore_api;

                    GRANT SELECT, INSERT ON TABLE public.sacco_loan_applications TO onecore_api;
                    REVOKE UPDATE, DELETE ON TABLE public.sacco_loan_applications FROM onecore_api;
                    GRANT UPDATE (
                        status, assessment_monthly_net_income, assessment_existing_monthly_debt,
                        assessment_monthly_installment, assessment_total_interest,
                        assessment_debt_service_ratio, assessment_recommendation, assessment_note,
                        assessed_by, assessed_at, decision_by, decided_at, decision_note,
                        disbursed_by, disbursed_at, updated_at
                    ) ON TABLE public.sacco_loan_applications TO onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE public.sacco_loan_applications_id_seq TO onecore_api;

                    GRANT SELECT, INSERT ON TABLE public.sacco_loan_ledger_entries TO onecore_api;
                    REVOKE UPDATE, DELETE ON TABLE public.sacco_loan_ledger_entries FROM onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE public.sacco_loan_ledger_entries_id_seq TO onecore_api;
                END IF;
            END
            $sacco_loan_grants$
        """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_sacco_loan_ledger_entries_immutable ON public.sacco_loan_ledger_entries")
        op.execute("DROP FUNCTION IF EXISTS public.onecore_reject_sacco_loan_ledger_mutation()")
        for table, policy in (
            ("sacco_loan_ledger_entries", "sacco_loan_ledger_entry_tenant_scope"),
            ("sacco_loan_applications", "sacco_loan_application_tenant_scope"),
            ("sacco_loan_products", "sacco_loan_product_tenant_scope"),
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table}")
            op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("uq_sacco_loan_one_disbursement", table_name="sacco_loan_ledger_entries")
    op.drop_index("ix_sacco_loan_ledger_org_application_created", table_name="sacco_loan_ledger_entries")
    op.drop_index("ix_sacco_loan_ledger_entries_branch_id", table_name="sacco_loan_ledger_entries")
    op.drop_index("ix_sacco_loan_ledger_entries_member_id", table_name="sacco_loan_ledger_entries")
    op.drop_index("ix_sacco_loan_ledger_entries_loan_application_id", table_name="sacco_loan_ledger_entries")
    op.drop_index("ix_sacco_loan_ledger_entries_organization_id", table_name="sacco_loan_ledger_entries")
    op.drop_table("sacco_loan_ledger_entries")
    op.drop_index("ix_sacco_loan_application_org_branch_status", table_name="sacco_loan_applications")
    op.drop_index("ix_sacco_loan_application_org_status", table_name="sacco_loan_applications")
    op.drop_index("ix_sacco_loan_application_org_member_created", table_name="sacco_loan_applications")
    op.drop_index("ix_sacco_loan_applications_branch_id", table_name="sacco_loan_applications")
    op.drop_index("ix_sacco_loan_applications_product_id", table_name="sacco_loan_applications")
    op.drop_index("ix_sacco_loan_applications_member_id", table_name="sacco_loan_applications")
    op.drop_index("ix_sacco_loan_applications_organization_id", table_name="sacco_loan_applications")
    op.drop_table("sacco_loan_applications")
    op.drop_index("ix_sacco_loan_product_org_active", table_name="sacco_loan_products")
    op.drop_index("ix_sacco_loan_products_organization_id", table_name="sacco_loan_products")
    op.drop_table("sacco_loan_products")
