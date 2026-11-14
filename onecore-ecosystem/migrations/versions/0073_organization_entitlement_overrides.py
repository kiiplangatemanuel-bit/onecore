"""Add per-organization subscription entitlement overrides."""
from alembic import op
import sqlalchemy as sa

revision = "0073_organization_entitlement_overrides"
down_revision = "0072_managed_file_versions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "organization_subscriptions",
        sa.Column("entitlements_override", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_column("organization_subscriptions", "entitlements_override")
