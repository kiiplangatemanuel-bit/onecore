"""Link CRM invoice-paid attribution events to their source accounting invoice."""
from alembic import op
import sqlalchemy as sa

revision = "0046_crm_attribution_accounting_invoice"
down_revision = "0045_accounting_invoice_crm_order"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("crm_campaign_attributions") as batch:
        batch.add_column(sa.Column("accounting_invoice_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_crm_attribution_accounting_invoice",
            "accounting_invoices",
            ["accounting_invoice_id"],
            ["id"],
        )
        batch.create_index(
            "uq_crm_attribution_org_invoice",
            ["organization_id", "accounting_invoice_id"],
            unique=True,
        )


def downgrade():
    with op.batch_alter_table("crm_campaign_attributions") as batch:
        batch.drop_index("uq_crm_attribution_org_invoice")
        batch.drop_constraint("fk_crm_attribution_accounting_invoice", type_="foreignkey")
        batch.drop_column("accounting_invoice_id")
