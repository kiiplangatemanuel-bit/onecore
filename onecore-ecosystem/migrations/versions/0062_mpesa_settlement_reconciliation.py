"""Persist tenant-scoped M-Pesa settlement statement reconciliation."""
from alembic import op
import sqlalchemy as sa

revision = "0062_mpesa_settlement_reconciliation"
down_revision = "0061_organization_owner_membership_bootstrap"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mpesa_settlement_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("source", sa.String(24), nullable=False, server_default="daraja_statement"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("status", sa.String(24), nullable=False, server_default="imported"),
        sa.Column("total_lines", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_lines", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("exception_lines", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("matched_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("imported_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_mpesa_settlement_org_key"),
    )
    op.create_index("ix_mpesa_settlement_batches_organization_id", "mpesa_settlement_batches", ["organization_id"])
    op.create_table(
        "mpesa_settlement_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("mpesa_settlement_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("receipt_number", sa.String(40), nullable=False),
        sa.Column("transaction_type", sa.String(12), nullable=False),
        sa.Column("transaction_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("account_reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("matched_type", sa.String(16), nullable=False, server_default=""),
        sa.Column("matched_id", sa.Integer(), nullable=True),
        sa.Column("expected_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="unmatched"),
        sa.Column("exception_detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mpesa_settlement_lines_organization_id", "mpesa_settlement_lines", ["organization_id"])
    op.create_index("ix_mpesa_settlement_lines_batch_id", "mpesa_settlement_lines", ["batch_id"])
    op.create_index("ix_mpesa_settlement_org_receipt", "mpesa_settlement_lines", ["organization_id", "receipt_number"])
    op.create_index("ix_mpesa_settlement_batch_status", "mpesa_settlement_lines", ["batch_id", "status"])
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in ("mpesa_settlement_batches", "mpesa_settlement_lines"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"""
                CREATE POLICY tenant_scope_access ON {table}
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
        # The dedicated API role is provisioned before migrations in production.
        # Grant only the CRUD and sequence rights required by these two tables.
        op.execute("""
            DO $
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_api') THEN
                    GRANT SELECT, INSERT, UPDATE ON TABLE
                        public.mpesa_settlement_batches, public.mpesa_settlement_lines
                        TO onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE
                        public.mpesa_settlement_batches_id_seq,
                        public.mpesa_settlement_lines_id_seq
                        TO onecore_api;
                END IF;
            END
            $
        """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in ("mpesa_settlement_lines", "mpesa_settlement_batches"):
            op.execute(f"DROP POLICY IF EXISTS tenant_scope_access ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("mpesa_settlement_lines")
    op.drop_table("mpesa_settlement_batches")
