"""Advanced POS device trust, sync operations and loyalty.
Revision ID: 0035
Revises: 0034
"""
from alembic import op
import sqlalchemy as sa

revision = "0035"
down_revision = "0034_inventory_retail_completion"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("pos_devices",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("branch_id",sa.String(36),sa.ForeignKey("branches.id"),nullable=False),
        sa.Column("device_key",sa.String(100),nullable=False),
        sa.Column("name",sa.String(120),nullable=False),
        sa.Column("platform",sa.String(80),nullable=False,server_default="browser"),
        sa.Column("token_digest",sa.String(64),nullable=False),
        sa.Column("status",sa.String(16),nullable=False,server_default="pending"),
        sa.Column("registered_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("approved_by",sa.Integer(),sa.ForeignKey("users.id")),
        sa.Column("approved_at",sa.DateTime(timezone=True)),
        sa.Column("revoked_at",sa.DateTime(timezone=True)),
        sa.Column("last_seen_at",sa.DateTime(timezone=True)),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("uq_pos_device_org_key","pos_devices",["organization_id","device_key"],unique=True)
    op.create_index("ix_pos_devices_organization_id","pos_devices",["organization_id"])
    op.create_index("ix_pos_devices_branch_id","pos_devices",["branch_id"])
    op.create_table("pos_sync_conflicts",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("branch_id",sa.String(36),sa.ForeignKey("branches.id"),nullable=False),
        sa.Column("device_id",sa.Integer(),sa.ForeignKey("pos_devices.id")),
        sa.Column("client_transaction_id",sa.String(100),nullable=False),
        sa.Column("conflict_type",sa.String(32),nullable=False),
        sa.Column("client_snapshot",sa.JSON(),nullable=False),
        sa.Column("server_snapshot",sa.JSON(),nullable=False),
        sa.Column("status",sa.String(16),nullable=False,server_default="open"),
        sa.Column("resolution",sa.String(24),nullable=False,server_default=""),
        sa.Column("resolution_note",sa.String(500),nullable=False,server_default=""),
        sa.Column("created_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("resolved_by",sa.Integer(),sa.ForeignKey("users.id")),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("resolved_at",sa.DateTime(timezone=True)))
    op.create_index("uq_pos_conflict_transaction","pos_sync_conflicts",["organization_id","client_transaction_id"],unique=True)
    op.create_index("ix_pos_sync_conflicts_organization_id","pos_sync_conflicts",["organization_id"])
    op.create_index("ix_pos_sync_conflicts_branch_id","pos_sync_conflicts",["branch_id"])
    op.create_table("pos_sync_events",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("branch_id",sa.String(36),sa.ForeignKey("branches.id"),nullable=False),
        sa.Column("device_id",sa.Integer(),sa.ForeignKey("pos_devices.id")),
        sa.Column("event_id",sa.String(100),nullable=False),
        sa.Column("transaction_id",sa.String(100),nullable=False,server_default=""),
        sa.Column("state",sa.String(20),nullable=False),
        sa.Column("attempt",sa.Integer(),nullable=False,server_default="1"),
        sa.Column("error_code",sa.String(80),nullable=False,server_default=""),
        sa.Column("error_message",sa.String(500),nullable=False,server_default=""),
        sa.Column("occurred_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("uq_pos_sync_event","pos_sync_events",["organization_id","event_id"],unique=True)
    op.create_index("ix_pos_sync_events_organization_id","pos_sync_events",["organization_id"])
    op.create_index("ix_pos_sync_events_branch_id","pos_sync_events",["branch_id"])
    op.create_table("pos_customers",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("customer_ref",sa.String(100),nullable=False),
        sa.Column("full_name",sa.String(160),nullable=False),
        sa.Column("phone",sa.String(32),nullable=False,server_default=""),
        sa.Column("email",sa.String(254),nullable=False,server_default=""),
        sa.Column("membership_number",sa.String(40),nullable=False),
        sa.Column("tier",sa.String(24),nullable=False,server_default="standard"),
        sa.Column("points_balance",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("is_active",sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("uq_pos_customer_ref","pos_customers",["organization_id","customer_ref"],unique=True)
    op.create_index("uq_pos_membership","pos_customers",["organization_id","membership_number"],unique=True)
    op.create_index("ix_pos_customers_organization_id","pos_customers",["organization_id"])
    op.create_table("pos_loyalty_entries",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("customer_id",sa.Integer(),sa.ForeignKey("pos_customers.id"),nullable=False),
        sa.Column("sale_id",sa.Integer(),sa.ForeignKey("pos_sales.id")),
        sa.Column("entry_key",sa.String(100),nullable=False),
        sa.Column("points_delta",sa.Integer(),nullable=False),
        sa.Column("entry_type",sa.String(20),nullable=False),
        sa.Column("note",sa.String(300),nullable=False,server_default=""),
        sa.Column("created_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("uq_pos_loyalty_entry_key","pos_loyalty_entries",["organization_id","entry_key"],unique=True)
    op.create_index("ix_pos_loyalty_entries_organization_id","pos_loyalty_entries",["organization_id"])
    op.create_index("ix_pos_loyalty_entries_customer_id","pos_loyalty_entries",["customer_id"])


def downgrade():
    op.drop_table("pos_loyalty_entries")
    op.drop_table("pos_customers")
    op.drop_table("pos_sync_events")
    op.drop_table("pos_sync_conflicts")
    op.drop_table("pos_devices")
