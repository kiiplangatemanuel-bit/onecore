"""Add tenant-isolated SACCO loan origination, guarantors, collateral and projected schedules."""
from alembic import op
import sqlalchemy as sa

revision = "0068_sacco_loan_origination"
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
        sa.Column("branch_id", sa.String(length=36), sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("minimum_principal", sa.Numeric(18, 2), nullable=False),
        sa.Column("maximum_principal", sa.Numeric(18, 2), nullable=False),
        sa.Column("annual_interest_rate_bps", sa.Integer(), nullable=False),
        sa.Column("minimum_term_months", sa.Integer(), nullable=False),
        sa.Column("maximum_term_months", sa.Integer(), nullable=False),
        sa.Column("minimum_guarantors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("maximum_debt_service_ratio_bps", sa.Integer(), nullable=False, server_default="4000"),
        sa.Column("requires_collateral", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "id", name="uq_sacco_loan_product_org_id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_sacco_loan_product_org_code"),
        sa.CheckConstraint("minimum_principal > 0 AND maximum_principal >= minimum_principal", name="ck_sacco_loan_product_principal_range"),
        sa.CheckConstraint("annual_interest_rate_bps BETWEEN 0 AND 6000", name="ck_sacco_loan_product_interest_rate"),
        sa.CheckConstraint("minimum_term_months BETWEEN 1 AND 120 AND maximum_term_months BETWEEN minimum_term_months AND 120", name="ck_sacco_loan_product_term_range"),
        sa.CheckConstraint("minimum_guarantors BETWEEN 0 AND 5", name="ck_sacco_loan_product_guarantors"),
        sa.CheckConstraint("maximum_debt_service_ratio_bps BETWEEN 1000 AND 8000", name="ck_sacco_loan_product_dsr"),
    )
    op.create_index("ix_sacco_loan_products_organization_id", "sacco_loan_products", ["organization_id"])
    op.create_index("ix_sacco_loan_products_branch_id", "sacco_loan_products", ["branch_id"])
    op.create_index("ix_sacco_loan_product_org_active", "sacco_loan_products", ["organization_id", "is_active"])
    op.create_index("ix_sacco_loan_product_org_branch", "sacco_loan_products", ["organization_id", "branch_id"])

    op.create_table(
        "sacco_loan_applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.String(length=36), sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("principal", sa.Numeric(18, 2), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=500), nullable=False),
        sa.Column("monthly_net_income", sa.Numeric(18, 2), nullable=False),
        sa.Column("monthly_existing_debt", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("first_repayment_date", sa.Date(), nullable=False),
        sa.Column("assessment_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("debt_service_ratio_bps", sa.Integer(), nullable=True),
        sa.Column("estimated_monthly_installment", sa.Numeric(18, 2), nullable=True),
        sa.Column("assessment_note", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("assessed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending_assessment"),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
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
        sa.CheckConstraint("principal > 0 AND term_months BETWEEN 1 AND 120", name="ck_sacco_loan_application_terms"),
        sa.CheckConstraint("monthly_net_income > 0 AND monthly_existing_debt >= 0", name="ck_sacco_loan_application_income"),
        sa.CheckConstraint("assessment_status IN ('pending', 'eligible', 'ineligible')", name="ck_sacco_loan_application_assessment"),
        sa.CheckConstraint("status IN ('pending_assessment', 'pending_guarantors', 'pending_approval', 'approved_pending_disbursement', 'rejected')", name="ck_sacco_loan_application_status"),
    )
    op.create_index("ix_sacco_loan_applications_organization_id", "sacco_loan_applications", ["organization_id"])
    op.create_index("ix_sacco_loan_applications_product_id", "sacco_loan_applications", ["product_id"])
    op.create_index("ix_sacco_loan_applications_member_id", "sacco_loan_applications", ["member_id"])
    op.create_index("ix_sacco_loan_applications_branch_id", "sacco_loan_applications", ["branch_id"])
    op.create_index("ix_sacco_loan_application_org_status", "sacco_loan_applications", ["organization_id", "status", "created_at"])
    op.create_index("ix_sacco_loan_application_org_member", "sacco_loan_applications", ["organization_id", "member_id", "created_at"])
    op.create_index("ix_sacco_loan_application_org_branch", "sacco_loan_applications", ["organization_id", "branch_id"])

    op.create_table(
        "sacco_loan_guarantors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("guaranteed_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("consent_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("consent_method", sa.String(length=32), nullable=True),
        sa.Column("consent_reference", sa.String(length=120), nullable=True),
        sa.Column("consent_note", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("consent_recorded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "id", name="uq_sacco_loan_guarantor_org_id"),
        sa.UniqueConstraint("organization_id", "application_id", "member_id", name="uq_sacco_loan_guarantor_application_member"),
        sa.ForeignKeyConstraint(
            ["organization_id", "application_id"], ["sacco_loan_applications.organization_id", "sacco_loan_applications.id"],
            ondelete="CASCADE", name="fk_sacco_loan_guarantor_application_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "member_id"], ["sacco_members.organization_id", "sacco_members.id"],
            ondelete="RESTRICT", name="fk_sacco_loan_guarantor_member_tenant",
        ),
        sa.CheckConstraint("guaranteed_amount > 0", name="ck_sacco_loan_guarantor_amount"),
        sa.CheckConstraint("consent_status IN ('pending', 'accepted', 'rejected')", name="ck_sacco_loan_guarantor_status"),
    )
    op.create_index("ix_sacco_loan_guarantors_organization_id", "sacco_loan_guarantors", ["organization_id"])
    op.create_index("ix_sacco_loan_guarantors_application_id", "sacco_loan_guarantors", ["application_id"])
    op.create_index("ix_sacco_loan_guarantors_member_id", "sacco_loan_guarantors", ["member_id"])
    op.create_index("ix_sacco_loan_guarantor_org_application", "sacco_loan_guarantors", ["organization_id", "application_id", "consent_status"])

    op.create_table(
        "sacco_loan_collateral",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("collateral_type", sa.String(length=40), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("declared_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("document_reference", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending_verification"),
        sa.Column("verification_note", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("verified_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "id", name="uq_sacco_loan_collateral_org_id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "application_id"], ["sacco_loan_applications.organization_id", "sacco_loan_applications.id"],
            ondelete="CASCADE", name="fk_sacco_loan_collateral_application_tenant",
        ),
        sa.CheckConstraint("declared_value > 0", name="ck_sacco_loan_collateral_value"),
        sa.CheckConstraint("status IN ('pending_verification', 'verified', 'rejected')", name="ck_sacco_loan_collateral_status"),
    )
    op.create_index("ix_sacco_loan_collateral_organization_id", "sacco_loan_collateral", ["organization_id"])
    op.create_index("ix_sacco_loan_collateral_application_id", "sacco_loan_collateral", ["application_id"])
    op.create_index("ix_sacco_loan_collateral_org_application", "sacco_loan_collateral", ["organization_id", "application_id", "status"])

    op.create_table(
        "sacco_loan_installments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("installment_number", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("principal_due", sa.Numeric(18, 2), nullable=False),
        sa.Column("interest_due", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_due", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="projected"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id", "application_id"], ["sacco_loan_applications.organization_id", "sacco_loan_applications.id"],
            ondelete="CASCADE", name="fk_sacco_loan_installment_application_tenant",
        ),
        sa.UniqueConstraint("organization_id", "application_id", "installment_number", name="uq_sacco_loan_installment_number"),
        sa.CheckConstraint("installment_number BETWEEN 1 AND 120", name="ck_sacco_loan_installment_number"),
        sa.CheckConstraint("principal_due >= 0 AND interest_due >= 0 AND total_due > 0 AND ROUND(total_due, 2) = ROUND(principal_due + interest_due, 2)", name="ck_sacco_loan_installment_amounts"),
        sa.CheckConstraint("status IN ('projected', 'due', 'paid', 'partially_paid', 'overdue', 'waived')", name="ck_sacco_loan_installment_status"),
    )
    op.create_index("ix_sacco_loan_installments_organization_id", "sacco_loan_installments", ["organization_id"])
    op.create_index("ix_sacco_loan_installments_application_id", "sacco_loan_installments", ["application_id"])
    op.create_index("ix_sacco_loan_installment_org_application_due", "sacco_loan_installments", ["organization_id", "application_id", "due_date"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table, policy in (
            ("sacco_loan_products", "sacco_loan_product_tenant_scope"),
            ("sacco_loan_applications", "sacco_loan_application_tenant_scope"),
            ("sacco_loan_guarantors", "sacco_loan_guarantor_tenant_scope"),
            ("sacco_loan_collateral", "sacco_loan_collateral_tenant_scope"),
            ("sacco_loan_installments", "sacco_loan_installment_tenant_scope"),
        ):
            _tenant_policy(table, policy)

        op.execute("""
            DO $sacco_loan_grants$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_api') THEN
                    GRANT SELECT, INSERT ON TABLE public.sacco_loan_products TO onecore_api;
                    REVOKE UPDATE, DELETE ON TABLE public.sacco_loan_products FROM onecore_api;
                    GRANT SELECT, INSERT ON TABLE public.sacco_loan_applications TO onecore_api;
                    REVOKE UPDATE, DELETE ON TABLE public.sacco_loan_applications FROM onecore_api;
                    GRANT UPDATE (
                        assessment_status, debt_service_ratio_bps, estimated_monthly_installment,
                        assessment_note, assessed_by, assessed_at, status, decided_by,
                        decided_at, decision_note, updated_at
                    ) ON TABLE public.sacco_loan_applications TO onecore_api;
                    GRANT SELECT, INSERT ON TABLE public.sacco_loan_guarantors TO onecore_api;
                    REVOKE UPDATE, DELETE ON TABLE public.sacco_loan_guarantors FROM onecore_api;
                    GRANT UPDATE (
                        consent_status, consent_method, consent_reference, consent_note,
                        consent_recorded_by, consent_at
                    ) ON TABLE public.sacco_loan_guarantors TO onecore_api;
                    GRANT SELECT, INSERT ON TABLE public.sacco_loan_collateral TO onecore_api;
                    REVOKE UPDATE, DELETE ON TABLE public.sacco_loan_collateral FROM onecore_api;
                    GRANT UPDATE (
                        status, verification_note, verified_by, verified_at
                    ) ON TABLE public.sacco_loan_collateral TO onecore_api;
                    GRANT SELECT, INSERT ON TABLE public.sacco_loan_installments TO onecore_api;
                    REVOKE UPDATE, DELETE ON TABLE public.sacco_loan_installments FROM onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE public.sacco_loan_products_id_seq TO onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE public.sacco_loan_applications_id_seq TO onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE public.sacco_loan_guarantors_id_seq TO onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE public.sacco_loan_collateral_id_seq TO onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE public.sacco_loan_installments_id_seq TO onecore_api;
                END IF;
            END
            $sacco_loan_grants$
        """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table, policy in (
            ("sacco_loan_installments", "sacco_loan_installment_tenant_scope"),
            ("sacco_loan_collateral", "sacco_loan_collateral_tenant_scope"),
            ("sacco_loan_guarantors", "sacco_loan_guarantor_tenant_scope"),
            ("sacco_loan_applications", "sacco_loan_application_tenant_scope"),
            ("sacco_loan_products", "sacco_loan_product_tenant_scope"),
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table}")
            op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_sacco_loan_installment_org_application_due", table_name="sacco_loan_installments")
    op.drop_index("ix_sacco_loan_installments_application_id", table_name="sacco_loan_installments")
    op.drop_index("ix_sacco_loan_installments_organization_id", table_name="sacco_loan_installments")
    op.drop_table("sacco_loan_installments")
    op.drop_index("ix_sacco_loan_collateral_org_application", table_name="sacco_loan_collateral")
    op.drop_index("ix_sacco_loan_collateral_application_id", table_name="sacco_loan_collateral")
    op.drop_index("ix_sacco_loan_collateral_organization_id", table_name="sacco_loan_collateral")
    op.drop_table("sacco_loan_collateral")
    op.drop_index("ix_sacco_loan_guarantor_org_application", table_name="sacco_loan_guarantors")
    op.drop_index("ix_sacco_loan_guarantors_member_id", table_name="sacco_loan_guarantors")
    op.drop_index("ix_sacco_loan_guarantors_application_id", table_name="sacco_loan_guarantors")
    op.drop_index("ix_sacco_loan_guarantors_organization_id", table_name="sacco_loan_guarantors")
    op.drop_table("sacco_loan_guarantors")
    op.drop_index("ix_sacco_loan_application_org_branch", table_name="sacco_loan_applications")
    op.drop_index("ix_sacco_loan_application_org_member", table_name="sacco_loan_applications")
    op.drop_index("ix_sacco_loan_application_org_status", table_name="sacco_loan_applications")
    op.drop_index("ix_sacco_loan_applications_branch_id", table_name="sacco_loan_applications")
    op.drop_index("ix_sacco_loan_applications_member_id", table_name="sacco_loan_applications")
    op.drop_index("ix_sacco_loan_applications_product_id", table_name="sacco_loan_applications")
    op.drop_index("ix_sacco_loan_applications_organization_id", table_name="sacco_loan_applications")
    op.drop_table("sacco_loan_applications")
    op.drop_index("ix_sacco_loan_product_org_branch", table_name="sacco_loan_products")
    op.drop_index("ix_sacco_loan_product_org_active", table_name="sacco_loan_products")
    op.drop_index("ix_sacco_loan_products_branch_id", table_name="sacco_loan_products")
    op.drop_index("ix_sacco_loan_products_organization_id", table_name="sacco_loan_products")
    op.drop_table("sacco_loan_products")
