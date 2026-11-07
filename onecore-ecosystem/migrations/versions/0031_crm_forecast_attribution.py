"""CRM forecasting, quotas, attribution and scheduler health."""
from alembic import op
import sqlalchemy as sa
revision = "0031_crm_forecast_attribution"
down_revision = "0030_crm_healthcare_controls"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("crm_leads", sa.Column("source_campaign_id", sa.Integer(), sa.ForeignKey("crm_campaigns.id"), nullable=True))
    op.create_index("ix_crm_lead_source_campaign", "crm_leads", ["organization_id", "source_campaign_id"])
    op.add_column("crm_leads", sa.Column("expected_close_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("crm_leads", sa.Column("probability_override", sa.Numeric(5, 2), nullable=True))
    op.add_column("crm_leads", sa.Column("actual_closed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_crm_lead_org_close_date", "crm_leads", ["organization_id", "expected_close_date"])
    op.add_column("crm_campaigns", sa.Column("budget_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("crm_campaigns", sa.Column("budget_currency", sa.String(3), nullable=False, server_default="KES"))
    op.create_table("crm_forecast_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False, unique=True),
        sa.Column("stage_probabilities", sa.JSON(), nullable=False),
        sa.Column("scenario_multipliers", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_crm_forecast_settings_organization_id", "crm_forecast_settings", ["organization_id"])
    op.create_table("crm_sales_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("period_type", sa.String(12), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rep_key", sa.String(32), nullable=False, server_default="team"),
        sa.Column("assigned_to", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("target_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_crm_sales_targets_organization_id", "crm_sales_targets", ["organization_id"])
    op.create_index("ix_crm_target_org_period_rep_currency", "crm_sales_targets",
        ["organization_id", "period_type", "period_start", "rep_key", "currency"], unique=True)
    op.create_table("crm_forecast_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("period_type", sa.String(12), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rep_key", sa.String(32), nullable=False, server_default="team"),
        sa.Column("assigned_to", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("scenario", sa.String(16), nullable=False),
        sa.Column("forecast_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("opportunity_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False))
    op.create_index("ix_crm_forecast_snapshots_organization_id", "crm_forecast_snapshots", ["organization_id"])
    op.create_index("ix_crm_forecast_snapshot_period", "crm_forecast_snapshots",
        ["organization_id", "period_type", "period_start", "snapshot_at"])
    op.create_table("crm_campaign_attributions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("crm_campaigns.id"), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id"), nullable=False),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("crm_leads.id"), nullable=True),
        sa.Column("sales_order_id", sa.Integer(), sa.ForeignKey("crm_sales_orders.id"), nullable=True),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("revenue_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False))
    op.create_index("ix_crm_campaign_attributions_organization_id", "crm_campaign_attributions", ["organization_id"])
    op.create_index("ix_crm_attribution_org_idempotency", "crm_campaign_attributions",
        ["organization_id", "idempotency_key"], unique=True)
    op.create_index("ix_crm_attribution_campaign_contact", "crm_campaign_attributions",
        ["organization_id", "campaign_id", "contact_id"])
    op.create_table("crm_worker_heartbeats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("worker_name", sa.String(80), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(500), nullable=False, server_default=""))
    op.create_index("ix_crm_worker_heartbeats_organization_id", "crm_worker_heartbeats", ["organization_id"])
    op.create_index("ix_crm_worker_org_name", "crm_worker_heartbeats",
        ["organization_id", "worker_name"], unique=True)

def downgrade():
    op.drop_table("crm_worker_heartbeats")
    op.drop_table("crm_campaign_attributions")
    op.drop_table("crm_forecast_snapshots")
    op.drop_table("crm_sales_targets")
    op.drop_table("crm_forecast_settings")
    op.drop_column("crm_campaigns", "budget_currency")
    op.drop_column("crm_campaigns", "budget_amount")
    op.drop_index("ix_crm_lead_org_close_date", table_name="crm_leads")
    op.drop_column("crm_leads", "actual_closed_at")
    op.drop_column("crm_leads", "probability_override")
    op.drop_column("crm_leads", "expected_close_date")
    op.drop_index("ix_crm_lead_source_campaign", table_name="crm_leads")
    op.drop_column("crm_leads", "source_campaign_id")
