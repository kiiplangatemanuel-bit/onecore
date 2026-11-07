"""Trusted POS devices, offline conflict resolution, customer loyalty and peripherals."""
from alembic import op
import sqlalchemy as sa

revision = "0035_pos_offline_loyalty_devices"
down_revision = "0034_inventory_retail_completion"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("pos_devices",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("branch_id",sa.String(36),sa.ForeignKey("branches.id"),nullable=False),
        sa.Column("device_key",sa.String(100),nullable=False),sa.Column("name",sa.String(120),nullable=False),
        sa.Column("platform",sa.String(40),nullable=False,server_default="browser"),
        sa.Column("credential_hash",sa.String(64),nullable=False),sa.Column("status",sa.String(20),nullable=False,server_default="pending"),
        sa.Column("offline_until",sa.DateTime(timezone=True)),sa.Column("last_seen_at",sa.DateTime(timezone=True)),
        sa.Column("last_sync_at",sa.DateTime(timezone=True)),sa.Column("last_sync_status",sa.String(24),nullable=False,server_default="never"),
        sa.Column("last_sync_error",sa.Text(),nullable=False,server_default=""),sa.Column("created_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("revoked_by",sa.Integer(),sa.ForeignKey("users.id")),sa.Column("revoked_at",sa.DateTime(timezone=True)),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("uq_pos_device_org_key","pos_devices",["organization_id","device_key"],unique=True)
    op.create_index("ix_pos_devices_organization_id","pos_devices",["organization_id"])
    op.create_index("ix_pos_devices_branch_id","pos_devices",["branch_id"])
    op.create_table("pos_offline_conflicts",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("branch_id",sa.String(36),sa.ForeignKey("branches.id"),nullable=False),sa.Column("device_id",sa.Integer(),sa.ForeignKey("pos_devices.id"),nullable=False),
        sa.Column("shift_id",sa.Integer(),sa.ForeignKey("pos_shifts.id"),nullable=False),sa.Column("client_transaction_id",sa.String(100),nullable=False),
        sa.Column("conflict_type",sa.String(40),nullable=False),sa.Column("server_snapshot",sa.JSON(),nullable=False),
        sa.Column("client_snapshot",sa.JSON(),nullable=False),sa.Column("status",sa.String(20),nullable=False,server_default="pending"),
        sa.Column("resolution",sa.String(32),nullable=False,server_default=""),sa.Column("resolution_note",sa.String(500),nullable=False,server_default=""),
        sa.Column("resolved_by",sa.Integer(),sa.ForeignKey("users.id")),sa.Column("resolved_at",sa.DateTime(timezone=True)),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("uq_pos_conflict_transaction","pos_offline_conflicts",["organization_id","device_id","client_transaction_id"],unique=True)
    op.create_index("ix_pos_offline_conflicts_organization_id","pos_offline_conflicts",["organization_id"])
    op.create_index("ix_pos_offline_conflicts_branch_id","pos_offline_conflicts",["branch_id"])
    op.create_index("ix_pos_offline_conflicts_device_id","pos_offline_conflicts",["device_id"])
    op.create_index("ix_pos_offline_conflicts_shift_id","pos_offline_conflicts",["shift_id"])
    op.create_table("pos_customers",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("branch_id",sa.String(36),sa.ForeignKey("branches.id")),sa.Column("customer_number",sa.String(40),nullable=False),
        sa.Column("full_name",sa.String(180),nullable=False),sa.Column("phone",sa.String(32),nullable=False,server_default=""),
        sa.Column("email",sa.String(320),nullable=False,server_default=""),sa.Column("membership_tier",sa.String(24),nullable=False,server_default="standard"),
        sa.Column("points_balance",sa.Integer(),nullable=False,server_default="0"),sa.Column("lifetime_spend",sa.Numeric(18,2),nullable=False,server_default="0"),
        sa.Column("is_active",sa.Boolean(),nullable=False,server_default=sa.true()),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("uq_pos_customer_number","pos_customers",["organization_id","customer_number"],unique=True)
    op.create_index("ix_pos_customers_organization_id","pos_customers",["organization_id"])
    op.create_index("ix_pos_customers_branch_id","pos_customers",["branch_id"])
    op.create_table("pos_loyalty_entries",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("customer_id",sa.Integer(),sa.ForeignKey("pos_customers.id"),nullable=False),sa.Column("sale_id",sa.Integer(),sa.ForeignKey("pos_sales.id")),
        sa.Column("entry_type",sa.String(16),nullable=False),sa.Column("points_delta",sa.Integer(),nullable=False),
        sa.Column("idempotency_key",sa.String(100),nullable=False),sa.Column("note",sa.String(300),nullable=False,server_default=""),
        sa.Column("created_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("uq_pos_loyalty_org_key","pos_loyalty_entries",["organization_id","idempotency_key"],unique=True)
    op.create_index("ix_pos_loyalty_entries_organization_id","pos_loyalty_entries",["organization_id"])
    op.create_index("ix_pos_loyalty_entries_customer_id","pos_loyalty_entries",["customer_id"])
    op.create_index("ix_pos_loyalty_entries_sale_id","pos_loyalty_entries",["sale_id"])
    op.create_table("pos_peripheral_commands",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("branch_id",sa.String(36),sa.ForeignKey("branches.id"),nullable=False),sa.Column("device_id",sa.Integer(),sa.ForeignKey("pos_devices.id"),nullable=False),
        sa.Column("sale_id",sa.Integer(),sa.ForeignKey("pos_sales.id")),sa.Column("peripheral_type",sa.String(20),nullable=False),
        sa.Column("command",sa.String(30),nullable=False),sa.Column("payload",sa.JSON(),nullable=False),sa.Column("status",sa.String(20),nullable=False,server_default="queued"),
        sa.Column("result",sa.JSON(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("acknowledged_at",sa.DateTime(timezone=True)))
    for col in ["organization_id","branch_id","device_id"]:
        op.create_index("ix_pos_peripheral_commands_"+col,"pos_peripheral_commands",[col])
    op.create_table("pos_customer_sales",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("customer_id",sa.Integer(),sa.ForeignKey("pos_customers.id"),nullable=False),sa.Column("sale_id",sa.Integer(),sa.ForeignKey("pos_sales.id"),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("uq_pos_customer_sale","pos_customer_sales",["organization_id","sale_id"],unique=True)
    op.create_index("ix_pos_customer_sales_organization_id","pos_customer_sales",["organization_id"])
    op.create_index("ix_pos_customer_sales_customer_id","pos_customer_sales",["customer_id"])
    op.create_index("ix_pos_customer_sales_sale_id","pos_customer_sales",["sale_id"])

def downgrade():
    op.drop_table("pos_customer_sales")
    op.drop_table("pos_peripheral_commands")
    op.drop_table("pos_loyalty_entries")
    op.drop_table("pos_customers")
    op.drop_table("pos_offline_conflicts")
    op.drop_table("pos_devices")
