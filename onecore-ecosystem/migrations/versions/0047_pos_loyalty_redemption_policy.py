"""Configure POS reward conversion and snapshot loyalty redemption at checkout."""
from alembic import op
import sqlalchemy as sa

revision = "0047_pos_loyalty_redemption_policy"
down_revision = "0046_crm_attribution_accounting_invoice"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "pos_sales",
        sa.Column("loyalty_points_redeemed", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "pos_sales",
        sa.Column("loyalty_discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "pos_sale_lines",
        sa.Column("loyalty_discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )
    op.create_table(
        "pos_loyalty_reward_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("earn_points_per_100_units", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("points_per_currency_unit", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("max_redemption_percent", sa.Numeric(5, 2), nullable=False, server_default="50.00"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("earn_points_per_100_units >= 0", name="ck_pos_loyalty_earn_rate_nonnegative"),
        sa.CheckConstraint("points_per_currency_unit > 0", name="ck_pos_loyalty_points_per_unit_positive"),
        sa.CheckConstraint("max_redemption_percent > 0 AND max_redemption_percent <= 100", name="ck_pos_loyalty_redemption_percent_range"),
    )
    op.create_index("uq_pos_loyalty_reward_policy_org", "pos_loyalty_reward_policies", ["organization_id"], unique=True)


def downgrade():
    op.drop_index("uq_pos_loyalty_reward_policy_org", table_name="pos_loyalty_reward_policies")
    op.drop_table("pos_loyalty_reward_policies")
    with op.batch_alter_table("pos_sale_lines") as batch:
        batch.drop_column("loyalty_discount_amount")
    with op.batch_alter_table("pos_sales") as batch:
        batch.drop_column("loyalty_discount_amount")
        batch.drop_column("loyalty_points_redeemed")
