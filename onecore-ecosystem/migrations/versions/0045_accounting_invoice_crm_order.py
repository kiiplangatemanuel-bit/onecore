"""Link customer invoices to CRM sales orders."""
from alembic import op
import sqlalchemy as sa

revision = "0045_accounting_invoice_crm_order"
down_revision = "0044_payroll_other_ded_account"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("accounting_invoices") as batch:
        batch.add_column(sa.Column("crm_sales_order_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_accounting_invoice_crm_sales_order",
            "crm_sales_orders",
            ["crm_sales_order_id"],
            ["id"],
        )
        batch.create_index(
            "ix_accounting_invoice_org_crm_order",
            ["organization_id", "crm_sales_order_id"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("accounting_invoices") as batch:
        batch.drop_index("ix_accounting_invoice_org_crm_order")
        batch.drop_constraint("fk_accounting_invoice_crm_sales_order", type_="foreignkey")
        batch.drop_column("crm_sales_order_id")
