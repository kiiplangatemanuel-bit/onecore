"""Add verified SACCO loan repayments, installment allocations and balanced subledger journals."""
from alembic import op
import sqlalchemy as sa

revision = "0070_sacco_loan_repayments"
down_revision = "0069_sacco_loan_disbursement"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sacco_loan_applications") as batch:
        batch.drop_constraint("ck_sacco_loan_application_status", type_="check")
        batch.create_check_constraint(
            "ck_sacco_loan_application_status",
            "status IN ('pending_assessment', 'pending_guarantors', 'pending_approval', "
            "'approved_pending_disbursement', 'active', 'settled', 'rejected')",
        )

    with op.batch_alter_table("sacco_loan_installments") as batch:
        batch.add_column(sa.Column("principal_paid", sa.Numeric(18, 2), nullable=False, server_default="0"))
        batch.add_column(sa.Column("interest_paid", sa.Numeric(18, 2), nullable=False, server_default="0"))
        batch.create_unique_constraint(
            "uq_sacco_loan_installment_org_app_id",
            ["organization_id", "application_id", "id"],
        )
        batch.create_check_constraint(
            "ck_sacco_loan_installment_principal_paid",
            "principal_paid >= 0 AND principal_paid <= principal_due",
        )
        batch.create_check_constraint(
            "ck_sacco_loan_installment_interest_paid",
            "interest_paid >= 0 AND interest_paid <= interest_due",
        )

    op.create_table(
        "sacco_loan_repayments",
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
        sa.UniqueConstraint("organization_id", "id", name="uq_sacco_loan_repayment_org_id"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_sacco_loan_repayment_org_idempotency"),
        sa.UniqueConstraint("organization_id", "channel", "external_reference", name="uq_sacco_loan_repayment_org_channel_reference"),
        sa.ForeignKeyConstraint(
            ["organization_id", "application_id"],
            ["sacco_loan_applications.organization_id", "sacco_loan_applications.id"],
            ondelete="RESTRICT", name="fk_sacco_loan_repayment_application_tenant",
        ),
        sa.CheckConstraint("amount > 0", name="ck_sacco_loan_repayment_amount"),
        sa.CheckConstraint("length(currency) = 3", name="ck_sacco_loan_repayment_currency"),
        sa.CheckConstraint(
            "length(trim(external_reference)) >= 3 AND external_reference = upper(external_reference)",
            name="ck_sacco_loan_repayment_reference",
        ),
        sa.CheckConstraint(
            "channel IN ('bank_transfer', 'mpesa', 'cash', 'cheque')",
            name="ck_sacco_loan_repayment_channel",
        ),
        sa.CheckConstraint(
            "status IN ('pending_verification', 'verified', 'rejected')",
            name="ck_sacco_loan_repayment_status",
        ),
    )
    op.create_index("ix_sacco_loan_repayments_organization_id", "sacco_loan_repayments", ["organization_id"])
    op.create_index("ix_sacco_loan_repayments_application_id", "sacco_loan_repayments", ["application_id"])
    op.create_index(
        "uq_sacco_loan_repayment_pending", "sacco_loan_repayments",
        ["organization_id", "application_id"], unique=True,
        postgresql_where=sa.text("status = 'pending_verification'"),
        sqlite_where=sa.text("status = 'pending_verification'"),
    )
    op.create_index(
        "ix_sacco_loan_repayment_org_application_date", "sacco_loan_repayments",
        ["organization_id", "application_id", "value_date"],
    )
    op.create_index(
        "ix_sacco_loan_repayment_org_created", "sacco_loan_repayments",
        ["organization_id", "created_at"],
    )

    op.create_table(
        "sacco_loan_repayment_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("repayment_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("installment_id", sa.Integer(), nullable=False),
        sa.Column("principal_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("interest_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "id", name="uq_sacco_loan_repayment_allocation_org_id"),
        sa.UniqueConstraint(
            "organization_id", "repayment_id", "installment_id",
            name="uq_sacco_loan_repayment_allocation_installment",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "repayment_id"],
            ["sacco_loan_repayments.organization_id", "sacco_loan_repayments.id"],
            ondelete="RESTRICT", name="fk_sacco_loan_repayment_allocation_receipt_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "application_id", "installment_id"],
            [
                "sacco_loan_installments.organization_id",
                "sacco_loan_installments.application_id",
                "sacco_loan_installments.id",
            ],
            ondelete="RESTRICT", name="fk_sacco_loan_repayment_allocation_installment_tenant",
        ),
        sa.CheckConstraint(
            "principal_amount >= 0 AND interest_amount >= 0 AND principal_amount + interest_amount > 0",
            name="ck_sacco_loan_repayment_allocation_amounts",
        ),
        sa.CheckConstraint("length(currency) = 3", name="ck_sacco_loan_repayment_allocation_currency"),
    )
    op.create_index(
        "ix_sacco_loan_repayment_allocations_organization_id",
        "sacco_loan_repayment_allocations", ["organization_id"],
    )
    op.create_index(
        "ix_sacco_loan_repayment_allocations_repayment_id",
        "sacco_loan_repayment_allocations", ["repayment_id"],
    )
    op.create_index(
        "ix_sacco_loan_repayment_allocations_application_id",
        "sacco_loan_repayment_allocations", ["application_id"],
    )
    op.create_index(
        "ix_sacco_loan_repayment_allocations_installment_id",
        "sacco_loan_repayment_allocations", ["installment_id"],
    )
    op.create_index(
        "ix_sacco_loan_repayment_allocation_org_application",
        "sacco_loan_repayment_allocations", ["organization_id", "application_id"],
    )

    op.create_table(
        "sacco_loan_repayment_journal_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("repayment_id", sa.Integer(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("account_code", sa.String(length=40), nullable=False),
        sa.Column("debit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("credit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("branch_id", sa.String(length=36), sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "id", name="uq_sacco_loan_repayment_journal_org_id"),
        sa.UniqueConstraint(
            "organization_id", "repayment_id", "line_number",
            name="uq_sacco_loan_repayment_journal_line",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "repayment_id"],
            ["sacco_loan_repayments.organization_id", "sacco_loan_repayments.id"],
            ondelete="RESTRICT", name="fk_sacco_loan_repayment_journal_receipt_tenant",
        ),
        sa.CheckConstraint(
            "account_code IN ('cash_clearing', 'loan_principal_receivable', 'loan_interest_income')",
            name="ck_sacco_loan_repayment_journal_account",
        ),
        sa.CheckConstraint(
            "debit >= 0 AND credit >= 0 AND ((debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0))",
            name="ck_sacco_loan_repayment_journal_one_side",
        ),
        sa.CheckConstraint("length(currency) = 3", name="ck_sacco_loan_repayment_journal_currency"),
    )
    op.create_index(
        "ix_sacco_loan_repayment_journal_lines_organization_id",
        "sacco_loan_repayment_journal_lines", ["organization_id"],
    )
    op.create_index(
        "ix_sacco_loan_repayment_journal_lines_repayment_id",
        "sacco_loan_repayment_journal_lines", ["repayment_id"],
    )
    op.create_index(
        "ix_sacco_loan_repayment_journal_lines_branch_id",
        "sacco_loan_repayment_journal_lines", ["branch_id"],
    )
    op.create_index(
        "ix_sacco_loan_repayment_journal_org_repayment",
        "sacco_loan_repayment_journal_lines", ["organization_id", "repayment_id"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        tenant_policy = """
            organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
            OR EXISTS (
                SELECT 1 FROM public.memberships m
                WHERE m.organization_id = {table}.organization_id
                  AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                  AND m.is_active = true
            )
            OR public.onecore_is_platform_admin()
        """
        for table, policy in (
            ("sacco_loan_repayments", "sacco_loan_repayment_tenant_scope"),
            ("sacco_loan_repayment_allocations", "sacco_loan_repayment_allocation_tenant_scope"),
            ("sacco_loan_repayment_journal_lines", "sacco_loan_repayment_journal_tenant_scope"),
        ):
            op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
            predicate = tenant_policy.format(table=table)
            op.execute(
                f"CREATE POLICY {policy} ON public.{table} FOR ALL "
                f"USING ({predicate}) WITH CHECK ({predicate})"
            )

        op.execute("""
            CREATE OR REPLACE FUNCTION public.onecore_guard_sacco_loan_repayment()
            RETURNS trigger LANGUAGE plpgsql AS $sacco_loan_repayment$
            DECLARE loan public.sacco_loan_applications%ROWTYPE;
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'SACCO loan repayment evidence is retained for audit';
                END IF;
                IF TG_OP = 'INSERT' THEN
                    IF NEW.status <> 'pending_verification'
                       OR NEW.reviewed_by IS NOT NULL OR NEW.reviewed_at IS NOT NULL
                       OR NEW.review_note <> '' THEN
                        RAISE EXCEPTION 'Repayment evidence must start pending independent verification';
                    END IF;
                    SELECT * INTO loan FROM public.sacco_loan_applications
                    WHERE organization_id = NEW.organization_id AND id = NEW.application_id;
                    IF NOT FOUND OR loan.status <> 'active' OR NOT EXISTS (
                        SELECT 1 FROM public.sacco_loan_disbursements d
                        WHERE d.organization_id = NEW.organization_id
                          AND d.application_id = NEW.application_id AND d.status = 'verified'
                    ) THEN
                        RAISE EXCEPTION 'Repayments require an active loan with verified disbursement evidence';
                    END IF;
                    RETURN NEW;
                END IF;
                IF OLD.status <> 'pending_verification'
                   OR NEW.status NOT IN ('verified', 'rejected') THEN
                    RAISE EXCEPTION 'Only pending repayment evidence can receive one final review';
                END IF;
                IF NEW.reviewed_by IS NULL OR NEW.reviewed_by = OLD.requested_by
                   OR NEW.reviewed_at IS NULL OR length(trim(NEW.review_note)) < 5 THEN
                    RAISE EXCEPTION 'Independent repayment review evidence is required';
                END IF;
                SELECT * INTO loan FROM public.sacco_loan_applications
                WHERE organization_id = NEW.organization_id AND id = NEW.application_id;
                IF NOT FOUND OR NEW.reviewed_by IN (loan.created_by, loan.assessed_by, loan.decided_by) THEN
                    RAISE EXCEPTION 'Repayment reviewer must be independent of loan origination and approval';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM public.memberships m
                    WHERE m.organization_id = NEW.organization_id
                      AND m.user_id = NEW.reviewed_by AND m.is_active = true
                      AND lower(m.role) IN ('org_admin', 'sacco_treasurer')
                ) THEN
                    RAISE EXCEPTION 'Repayment reviewer must have an active treasurer or organization-admin membership';
                END IF;
                RETURN NEW;
            END
            $sacco_loan_repayment$
        """)
        op.execute("""
            CREATE TRIGGER trg_sacco_loan_repayment_guard
            BEFORE INSERT OR UPDATE OR DELETE ON public.sacco_loan_repayments
            FOR EACH ROW EXECUTE FUNCTION public.onecore_guard_sacco_loan_repayment()
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION public.onecore_guard_sacco_loan_repayment_allocation()
            RETURNS trigger LANGUAGE plpgsql AS $sacco_loan_repayment_allocation$
            DECLARE
                receipt public.sacco_loan_repayments%ROWTYPE;
                installment public.sacco_loan_installments%ROWTYPE;
                receipt_allocated numeric(18,2);
                installment_principal numeric(18,2);
                installment_interest numeric(18,2);
            BEGIN
                IF TG_OP <> 'INSERT' THEN
                    RAISE EXCEPTION 'SACCO repayment allocations are immutable';
                END IF;
                SELECT * INTO receipt FROM public.sacco_loan_repayments
                WHERE organization_id = NEW.organization_id AND id = NEW.repayment_id;
                SELECT * INTO installment FROM public.sacco_loan_installments
                WHERE organization_id = NEW.organization_id
                  AND application_id = NEW.application_id AND id = NEW.installment_id;
                IF NOT FOUND OR receipt.id IS NULL OR receipt.status <> 'verified'
                   OR receipt.application_id <> NEW.application_id
                   OR receipt.currency <> NEW.currency OR installment.currency <> NEW.currency THEN
                    RAISE EXCEPTION 'Repayment allocation must reference a verified same-loan receipt and installment';
                END IF;
                SELECT COALESCE(sum(principal_amount + interest_amount), 0)
                INTO receipt_allocated FROM public.sacco_loan_repayment_allocations
                WHERE organization_id = NEW.organization_id AND repayment_id = NEW.repayment_id;
                IF receipt_allocated + NEW.principal_amount + NEW.interest_amount > receipt.amount THEN
                    RAISE EXCEPTION 'Repayment allocations exceed the receipt amount';
                END IF;
                SELECT COALESCE(sum(principal_amount), 0), COALESCE(sum(interest_amount), 0)
                INTO installment_principal, installment_interest
                FROM public.sacco_loan_repayment_allocations
                WHERE organization_id = NEW.organization_id AND installment_id = NEW.installment_id;
                IF installment_principal + NEW.principal_amount > installment.principal_due
                   OR installment_interest + NEW.interest_amount > installment.interest_due THEN
                    RAISE EXCEPTION 'Repayment allocation exceeds the contractual installment balance';
                END IF;
                RETURN NEW;
            END
            $sacco_loan_repayment_allocation$
        """)
        op.execute("""
            CREATE TRIGGER trg_sacco_loan_repayment_allocation_guard
            BEFORE INSERT OR UPDATE OR DELETE ON public.sacco_loan_repayment_allocations
            FOR EACH ROW EXECUTE FUNCTION public.onecore_guard_sacco_loan_repayment_allocation()
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION public.onecore_guard_sacco_loan_repayment_journal()
            RETURNS trigger LANGUAGE plpgsql AS $sacco_loan_repayment_journal$
            BEGIN
                IF TG_OP <> 'INSERT' THEN
                    RAISE EXCEPTION 'SACCO repayment journal lines are immutable';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM public.sacco_loan_repayments r
                    WHERE r.organization_id = NEW.organization_id
                      AND r.id = NEW.repayment_id AND r.status = 'verified'
                      AND r.currency = NEW.currency
                ) THEN
                    RAISE EXCEPTION 'Repayment journal lines require a verified same-currency receipt';
                END IF;
                RETURN NEW;
            END
            $sacco_loan_repayment_journal$
        """)
        op.execute("""
            CREATE TRIGGER trg_sacco_loan_repayment_journal_guard
            BEFORE INSERT OR UPDATE OR DELETE ON public.sacco_loan_repayment_journal_lines
            FOR EACH ROW EXECUTE FUNCTION public.onecore_guard_sacco_loan_repayment_journal()
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION public.onecore_assert_sacco_loan_repayment_journal_balanced()
            RETURNS trigger LANGUAGE plpgsql AS $sacco_loan_repayment_journal_balance$
            DECLARE
                target_org integer;
                target_repayment integer;
                line_count integer;
                debit_total numeric(18,2);
                credit_total numeric(18,2);
                receipt_amount numeric(18,2);
            BEGIN
                target_org := NEW.organization_id;
                target_repayment := NEW.repayment_id;
                SELECT count(*), COALESCE(sum(debit), 0), COALESCE(sum(credit), 0)
                INTO line_count, debit_total, credit_total
                FROM public.sacco_loan_repayment_journal_lines
                WHERE organization_id = target_org AND repayment_id = target_repayment;
                SELECT amount INTO receipt_amount FROM public.sacco_loan_repayments
                WHERE organization_id = target_org AND id = target_repayment AND status = 'verified';
                IF line_count < 2 OR debit_total <= 0 OR debit_total <> credit_total
                   OR debit_total <> receipt_amount THEN
                    RAISE EXCEPTION 'SACCO repayment subledger journal must balance to the verified receipt amount';
                END IF;
                RETURN NULL;
            END
            $sacco_loan_repayment_journal_balance$
        """)
        op.execute("""
            CREATE CONSTRAINT TRIGGER trg_sacco_loan_repayment_journal_balanced
            AFTER INSERT ON public.sacco_loan_repayment_journal_lines
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION public.onecore_assert_sacco_loan_repayment_journal_balanced()
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION public.onecore_guard_sacco_loan_installment_paid()
            RETURNS trigger LANGUAGE plpgsql AS $sacco_loan_installment_paid$
            DECLARE
                allocated_principal numeric(18,2);
                allocated_interest numeric(18,2);
            BEGIN
                IF NEW.principal_paid <> OLD.principal_paid OR NEW.interest_paid <> OLD.interest_paid THEN
                    SELECT COALESCE(sum(a.principal_amount), 0), COALESCE(sum(a.interest_amount), 0)
                    INTO allocated_principal, allocated_interest
                    FROM public.sacco_loan_repayment_allocations a
                    JOIN public.sacco_loan_repayments r
                      ON r.organization_id = a.organization_id AND r.id = a.repayment_id
                    WHERE a.organization_id = NEW.organization_id
                      AND a.installment_id = NEW.id AND r.status = 'verified';
                    IF NEW.principal_paid <> allocated_principal OR NEW.interest_paid <> allocated_interest THEN
                        RAISE EXCEPTION 'Installment paid totals must equal immutable verified repayment allocations';
                    END IF;
                END IF;
                IF NEW.status = 'paid' AND NEW.principal_paid + NEW.interest_paid <> NEW.total_due THEN
                    RAISE EXCEPTION 'Only fully allocated installments can be marked paid';
                END IF;
                IF NEW.status = 'partially_paid'
                   AND (NEW.principal_paid + NEW.interest_paid <= 0
                        OR NEW.principal_paid + NEW.interest_paid >= NEW.total_due) THEN
                    RAISE EXCEPTION 'Partially paid status requires a positive incomplete allocation';
                END IF;
                RETURN NEW;
            END
            $sacco_loan_installment_paid$
        """)
        op.execute("""
            CREATE TRIGGER trg_sacco_loan_installment_paid_guard
            BEFORE UPDATE ON public.sacco_loan_installments
            FOR EACH ROW EXECUTE FUNCTION public.onecore_guard_sacco_loan_installment_paid()
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION public.onecore_require_settled_sacco_loan()
            RETURNS trigger LANGUAGE plpgsql AS $sacco_loan_settled$
            BEGIN
                IF NEW.status = 'settled' AND EXISTS (
                    SELECT 1 FROM public.sacco_loan_installments i
                    WHERE i.organization_id = NEW.organization_id AND i.application_id = NEW.id
                      AND i.status NOT IN ('paid', 'waived')
                ) THEN
                    RAISE EXCEPTION 'A SACCO loan can be settled only after every installment is paid or waived';
                END IF;
                RETURN NEW;
            END
            $sacco_loan_settled$
        """)
        op.execute("""
            CREATE TRIGGER trg_sacco_loan_settled_guard
            BEFORE UPDATE OF status ON public.sacco_loan_applications
            FOR EACH ROW EXECUTE FUNCTION public.onecore_require_settled_sacco_loan()
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION public.onecore_assert_sacco_loan_repayment_allocated()
            RETURNS trigger LANGUAGE plpgsql AS $sacco_loan_repayment_allocated$
            DECLARE
                target_org integer;
                target_repayment integer;
                allocated numeric(18,2);
                expected numeric(18,2);
            BEGIN
                target_org := NEW.organization_id;
                target_repayment := NEW.id;
                IF NEW.status = 'verified' THEN
                    SELECT COALESCE(sum(principal_amount + interest_amount), 0)
                    INTO allocated FROM public.sacco_loan_repayment_allocations
                    WHERE organization_id = target_org AND repayment_id = target_repayment;
                    expected := NEW.amount;
                    IF allocated <> expected THEN
                        RAISE EXCEPTION 'Every verified repayment must be fully allocated to due installments';
                    END IF;
                END IF;
                RETURN NULL;
            END
            $sacco_loan_repayment_allocated$
        """)
        op.execute("""
            CREATE CONSTRAINT TRIGGER trg_sacco_loan_repayment_allocated
            AFTER UPDATE ON public.sacco_loan_repayments
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION public.onecore_assert_sacco_loan_repayment_allocated()
        """)
        op.execute("""
            DO $sacco_loan_repayment_grants$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_api') THEN
                    GRANT SELECT, INSERT ON TABLE public.sacco_loan_repayments,
                        public.sacco_loan_repayment_allocations,
                        public.sacco_loan_repayment_journal_lines TO onecore_api;
                    REVOKE UPDATE, DELETE ON TABLE public.sacco_loan_repayments,
                        public.sacco_loan_repayment_allocations,
                        public.sacco_loan_repayment_journal_lines FROM onecore_api;
                    GRANT UPDATE (status, reviewed_by, reviewed_at, review_note, updated_at)
                        ON TABLE public.sacco_loan_repayments TO onecore_api;
                    GRANT UPDATE (status, principal_paid, interest_paid)
                        ON TABLE public.sacco_loan_installments TO onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE public.sacco_loan_repayments_id_seq,
                        public.sacco_loan_repayment_allocations_id_seq,
                        public.sacco_loan_repayment_journal_lines_id_seq TO onecore_api;
                END IF;
            END
            $sacco_loan_repayment_grants$
        """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_sacco_loan_repayment_guard ON public.sacco_loan_repayments")
        op.execute("DROP FUNCTION IF EXISTS public.onecore_guard_sacco_loan_repayment()")
        op.execute("DROP TRIGGER IF EXISTS trg_sacco_loan_repayment_allocation_guard ON public.sacco_loan_repayment_allocations")
        op.execute("DROP FUNCTION IF EXISTS public.onecore_guard_sacco_loan_repayment_allocation()")
        op.execute("DROP TRIGGER IF EXISTS trg_sacco_loan_repayment_journal_guard ON public.sacco_loan_repayment_journal_lines")
        op.execute("DROP FUNCTION IF EXISTS public.onecore_guard_sacco_loan_repayment_journal()")
        op.execute("DROP TRIGGER IF EXISTS trg_sacco_loan_repayment_journal_balanced ON public.sacco_loan_repayment_journal_lines")
        op.execute("DROP FUNCTION IF EXISTS public.onecore_assert_sacco_loan_repayment_journal_balanced()")
        op.execute("DROP TRIGGER IF EXISTS trg_sacco_loan_installment_paid_guard ON public.sacco_loan_installments")
        op.execute("DROP FUNCTION IF EXISTS public.onecore_guard_sacco_loan_installment_paid()")
        op.execute("DROP TRIGGER IF EXISTS trg_sacco_loan_settled_guard ON public.sacco_loan_applications")
        op.execute("DROP FUNCTION IF EXISTS public.onecore_require_settled_sacco_loan()")
        op.execute("DROP TRIGGER IF EXISTS trg_sacco_loan_repayment_allocated ON public.sacco_loan_repayments")
        op.execute("DROP FUNCTION IF EXISTS public.onecore_assert_sacco_loan_repayment_allocated()")
        for table, policy in (
            ("sacco_loan_repayments", "sacco_loan_repayment_tenant_scope"),
            ("sacco_loan_repayment_allocations", "sacco_loan_repayment_allocation_tenant_scope"),
            ("sacco_loan_repayment_journal_lines", "sacco_loan_repayment_journal_tenant_scope"),
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table}")
            op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
        op.execute("""
            DO $sacco_loan_repayment_revoke$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_api') THEN
                    REVOKE UPDATE (status, principal_paid, interest_paid)
                        ON TABLE public.sacco_loan_installments FROM onecore_api;
                    GRANT UPDATE (status) ON TABLE public.sacco_loan_installments TO onecore_api;
                END IF;
            END
            $sacco_loan_repayment_revoke$
        """)

    op.drop_index("ix_sacco_loan_repayment_journal_org_repayment", table_name="sacco_loan_repayment_journal_lines")
    op.drop_index("ix_sacco_loan_repayment_journal_lines_branch_id", table_name="sacco_loan_repayment_journal_lines")
    op.drop_index("ix_sacco_loan_repayment_journal_lines_repayment_id", table_name="sacco_loan_repayment_journal_lines")
    op.drop_index("ix_sacco_loan_repayment_journal_lines_organization_id", table_name="sacco_loan_repayment_journal_lines")
    op.drop_table("sacco_loan_repayment_journal_lines")
    op.drop_index("ix_sacco_loan_repayment_allocation_org_application", table_name="sacco_loan_repayment_allocations")
    op.drop_index("ix_sacco_loan_repayment_allocations_installment_id", table_name="sacco_loan_repayment_allocations")
    op.drop_index("ix_sacco_loan_repayment_allocations_application_id", table_name="sacco_loan_repayment_allocations")
    op.drop_index("ix_sacco_loan_repayment_allocations_repayment_id", table_name="sacco_loan_repayment_allocations")
    op.drop_index("ix_sacco_loan_repayment_allocations_organization_id", table_name="sacco_loan_repayment_allocations")
    op.drop_table("sacco_loan_repayment_allocations")
    op.drop_index("ix_sacco_loan_repayment_org_created", table_name="sacco_loan_repayments")
    op.drop_index("ix_sacco_loan_repayment_org_application_date", table_name="sacco_loan_repayments")
    op.drop_index("uq_sacco_loan_repayment_pending", table_name="sacco_loan_repayments")
    op.drop_index("ix_sacco_loan_repayments_application_id", table_name="sacco_loan_repayments")
    op.drop_index("ix_sacco_loan_repayments_organization_id", table_name="sacco_loan_repayments")
    op.drop_table("sacco_loan_repayments")

    with op.batch_alter_table("sacco_loan_installments") as batch:
        batch.drop_constraint("ck_sacco_loan_installment_interest_paid", type_="check")
        batch.drop_constraint("ck_sacco_loan_installment_principal_paid", type_="check")
        batch.drop_constraint("uq_sacco_loan_installment_org_app_id", type_="unique")
        batch.drop_column("interest_paid")
        batch.drop_column("principal_paid")
    with op.batch_alter_table("sacco_loan_applications") as batch:
        batch.drop_constraint("ck_sacco_loan_application_status", type_="check")
        batch.create_check_constraint(
            "ck_sacco_loan_application_status",
            "status IN ('pending_assessment', 'pending_guarantors', 'pending_approval', "
            "'approved_pending_disbursement', 'active', 'rejected')",
        )
