"""Add FX posting/revaluation and statutory payroll remittance batches."""
from alembic import op
import sqlalchemy as sa

revision = "0063_fx_statutory_remittances"
down_revision = "0062_mpesa_settlement_reconciliation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "accounting_fx_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("rate_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("units_per_base", sa.Numeric(20, 10), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_accounting_fx_rate_org_currency_date_source", "accounting_fx_rates", ["organization_id","currency","rate_date","source"], unique=True)
    op.create_table(
        "accounting_fx_postings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id"), nullable=False, unique=True),
        sa.Column("rate_id", sa.Integer(), sa.ForeignKey("accounting_fx_rates.id"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("foreign_amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("base_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_accounting_fx_posting_org_key","accounting_fx_postings",["organization_id","idempotency_key"],unique=True)
    op.create_table(
        "accounting_fx_revaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id"), nullable=False, unique=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("valuation_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closing_rate", sa.Numeric(20, 10), nullable=False),
        sa.Column("total_gain", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_loss", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("position_snapshot", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_accounting_fx_revaluation_org_key","accounting_fx_revaluations",["organization_id","idempotency_key"],unique=True)
    op.create_table(
        "payroll_statutory_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("totals", sa.JSON(), nullable=False),
        sa.Column("employee_lines", sa.JSON(), nullable=False),
        sa.Column("source_run_ids", sa.JSON(), nullable=False),
        sa.Column("payment_journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id"), nullable=True, unique=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("paid_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("payment_reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_payroll_statutory_batch_org_key","payroll_statutory_batches",["organization_id","idempotency_key"],unique=True)
    bind=op.get_bind()
    if bind.dialect.name=="postgresql":
        for table in ("accounting_fx_rates","accounting_fx_postings","accounting_fx_revaluations","payroll_statutory_batches"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"""
                CREATE POLICY tenant_scope_access ON {table}
                USING (
                    EXISTS (
                        SELECT 1 FROM public.memberships m
                        WHERE m.organization_id = {table}.organization_id
                          AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.is_active = true
                    )
                    OR {table}.organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
                    OR public.onecore_is_platform_admin()
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
            op.execute(f"""
                DO $grant$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_api') THEN
                        GRANT SELECT, INSERT, UPDATE ON TABLE public.{table} TO onecore_api;
                        GRANT USAGE, SELECT ON SEQUENCE public.{table}_id_seq TO onecore_api;
                    END IF;
                END
                $grant$
            """)


def downgrade():
    bind=op.get_bind()
    if bind.dialect.name=="postgresql":
        for table in ("payroll_statutory_batches","accounting_fx_revaluations","accounting_fx_postings","accounting_fx_rates"):
            op.execute(f"DROP POLICY IF EXISTS tenant_scope_access ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("payroll_statutory_batches")
    op.drop_table("accounting_fx_revaluations")
    op.drop_table("accounting_fx_postings")
    op.drop_table("accounting_fx_rates")
