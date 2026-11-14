"""Merge subscription price snapshot and organization entitlement revisions."""

revision = "0074_merge_subscription_heads"
down_revision = (
    "0073_subscription_price_snapshot",
    "0073_organization_entitlement_overrides",
)
branch_labels = None
depends_on = None


def upgrade():
    # Both parent migrations are additive and independently reversible.
    pass


def downgrade():
    # Keep both parent revisions as heads when this merge is reversed.
    pass
