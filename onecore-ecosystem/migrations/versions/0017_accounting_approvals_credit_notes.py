"""Accounting invoice approvals and credit notes.

Revision ID: 0017_accounting_approvals_credit_notes
Revises: 0016_procurement_completion
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_accounting_approvals_credit_notes"
down_revision = "0016_procurement_completion"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "accounting_invoice_approvals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("accounting_invoices.id"), nullable=False),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approver_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("decision_note", sa.String(500), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_accounting_invoice_approvals_organization_id",
        "accounting_invoice_approvals", ["organization_id"])
    op.create_index("ix_accounting_invoice_approvals_invoice_id",
        "accounting_invoice_approvals", ["invoice_id"])
    op.create_index("ix_accounting_invoice_approval_org_invoice",
        "accounting_invoice_approvals", ["organization_id", "invoice_id"], unique=True)

    op.create_table(
        "accounting_credit_notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("accounting_invoices.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("credit_note_number", sa.String(60), nullable=False),
        sa.Column("issue_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("total", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("accounting_journals.id"), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("posted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("organization_id", "invoice_id", "branch_id"):
        op.create_index("ix_accounting_credit_notes_" + col, "accounting_credit_notes", [col])
    op.create_index("ix_accounting_credit_note_org_number", "accounting_credit_notes",
        ["organization_id", "credit_note_number"], unique=True)
    op.create_index("ix_accounting_credit_note_org_key", "accounting_credit_notes",
        ["organization_id", "idempotency_key"], unique=True)

    op.create_table(
        "accounting_credit_note_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("credit_note_id", sa.Integer(), sa.ForeignKey("accounting_credit_notes.id"), nullable=False),
        sa.Column("invoice_line_id", sa.Integer(), sa.ForeignKey("accounting_invoice_lines.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("total", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("organization_id", "credit_note_id", "invoice_line_id"):
        op.create_index("ix_accounting_credit_note_lines_" + col,
            "accounting_credit_note_lines", [col])


def downgrade():
    op.drop_table("accounting_credit_note_lines")
    op.drop_table("accounting_credit_notes")
    op.drop_table("accounting_invoice_approvals")
