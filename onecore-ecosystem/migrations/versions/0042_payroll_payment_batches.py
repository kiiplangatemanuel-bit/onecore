"""Controlled payroll payment batches and bank statement reconciliation."""
from alembic import op
import sqlalchemy as sa

revision = "0042_payroll_payment_batches"
down_revision = "0041_employee_overtime_policy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payroll_payment_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payroll_payment_batches_organization_id",
                    "payroll_payment_batches", ["organization_id"])
    op.create_index("uq_payroll_payment_batch_org_idempotency",
                    "payroll_payment_batches", ["organization_id", "idempotency_key"], unique=True)

    op.create_table(
        "payroll_payment_batch_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("payroll_payment_batches.id"), nullable=False),
        sa.Column("payroll_run_id", sa.Integer(), sa.ForeignKey("payroll_runs.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id")),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("payment_reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("settlement_journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id"), unique=True),
        sa.Column("paid_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payroll_payment_batch_items_organization_id",
                    "payroll_payment_batch_items", ["organization_id"])
    op.create_index("ix_payroll_payment_batch_items_batch_id",
                    "payroll_payment_batch_items", ["batch_id"])
    op.create_index("ix_payroll_payment_batch_items_payroll_run_id",
                    "payroll_payment_batch_items", ["payroll_run_id"])
    op.create_index("uq_payroll_batch_item_active_run",
                    "payroll_payment_batch_items", ["payroll_run_id"], unique=True,
                    sqlite_where=sa.text("status <> 'cancelled'"),
                    postgresql_where=sa.text("status <> 'cancelled'"))
    op.create_index("ix_payroll_payment_batch_items_branch_id",
                    "payroll_payment_batch_items", ["branch_id"])
    op.create_index("uq_payroll_batch_item_org_reference",
                    "payroll_payment_batch_items", ["organization_id", "payment_reference"],
                    unique=True, sqlite_where=sa.text("payment_reference <> ''"),
                    postgresql_where=sa.text("payment_reference <> ''"))
    op.create_index("ix_payroll_payment_batch_items_settlement_journal_id",
                    "payroll_payment_batch_items", ["settlement_journal_id"], unique=True)

    op.create_table(
        "payroll_bank_statement_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), sa.ForeignKey("accounting_accounts.id"), nullable=False),
        sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("status", sa.String(24), nullable=False, server_default="unmatched"),
        sa.Column("batch_item_id", sa.Integer(), sa.ForeignKey("payroll_payment_batch_items.id"), unique=True),
        sa.Column("match_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("imported_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("matched_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("matched_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payroll_bank_statement_lines_organization_id",
                    "payroll_bank_statement_lines", ["organization_id"])
    op.create_index("ix_payroll_bank_statement_lines_bank_account_id",
                    "payroll_bank_statement_lines", ["bank_account_id"])
    op.create_index("uq_payroll_bank_statement_fingerprint",
                    "payroll_bank_statement_lines",
                    ["organization_id", "bank_account_id", "transaction_date", "reference", "amount"],
                    unique=True)
    op.create_index("ix_payroll_bank_statement_lines_batch_item_id",
                    "payroll_bank_statement_lines", ["batch_item_id"], unique=True)


def downgrade():
    op.drop_table("payroll_bank_statement_lines")
    op.drop_table("payroll_payment_batch_items")
    op.drop_table("payroll_payment_batches")
