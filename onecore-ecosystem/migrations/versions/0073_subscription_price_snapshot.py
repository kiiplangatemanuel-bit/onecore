"""Snapshot plan price and interval on each subscription."""
from alembic import op
import sqlalchemy as sa

revision = "0073_subscription_price_snapshot"
down_revision = "0072_managed_file_versions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("organization_subscriptions", sa.Column("amount", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("organization_subscriptions", sa.Column("currency", sa.String(3), nullable=False, server_default="KES"))
    op.add_column("organization_subscriptions", sa.Column("billing_interval", sa.String(16), nullable=False, server_default="monthly"))


def downgrade():
    op.drop_column("organization_subscriptions", "billing_interval")
    op.drop_column("organization_subscriptions", "currency")
    op.drop_column("organization_subscriptions", "amount")
