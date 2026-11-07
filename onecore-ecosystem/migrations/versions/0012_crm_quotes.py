"""CRM quotes and itemized quote lines.

Revision ID: 0012_crm_quotes
Revises: 0011_accounting_bank_reconciliation
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_crm_quotes"
down_revision = "0011_accounting_bank_reconciliation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("crm_quotes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id"), nullable=False),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("crm_leads.id"), nullable=True),
        sa.Column("quote_number", sa.String(60), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("issue_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("total", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_crm_quotes_organization_id", "crm_quotes", ["organization_id"])
    op.create_index("ix_crm_quotes_branch_id", "crm_quotes", ["branch_id"])
    op.create_index("ix_crm_quotes_contact_id", "crm_quotes", ["contact_id"])
    op.create_index("ix_crm_quotes_lead_id", "crm_quotes", ["lead_id"])
    op.create_index("ix_crm_quote_org_number", "crm_quotes", ["organization_id", "quote_number"], unique=True)

    op.create_table("crm_quote_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("quote_id", sa.Integer(), sa.ForeignKey("crm_quotes.id"), nullable=False),
        sa.Column("description", sa.String(240), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_rate", sa.Numeric(7, 4), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("total", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_crm_quote_lines_organization_id", "crm_quote_lines", ["organization_id"])
    op.create_index("ix_crm_quote_lines_quote_id", "crm_quote_lines", ["quote_id"])


def downgrade():
    op.drop_table("crm_quote_lines")
    op.drop_table("crm_quotes")
