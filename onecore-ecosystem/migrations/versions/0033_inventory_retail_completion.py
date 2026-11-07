"""Inventory logistics, stock control and retail pricing."""
from alembic import op
import sqlalchemy as sa

revision = "0033_inventory_retail_completion"
down_revision = "0032_crm_forecast_attribution"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("inventory_warehouses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("code", sa.String(40), nullable=False), sa.Column("name", sa.String(180), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_inventory_warehouses_organization_id", "inventory_warehouses", ["organization_id"])
    op.create_index("ix_inventory_warehouses_branch_id", "inventory_warehouses", ["branch_id"])
    op.create_index("uq_inventory_warehouse_org_code", "inventory_warehouses", ["organization_id","code"], unique=True)
    op.add_column("inventory_stock_movements", sa.Column("warehouse_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("inventory_stock_movements") as batch_op:
        batch_op.create_foreign_key("fk_inventory_movement_warehouse", "inventory_warehouses", ["warehouse_id"], ["id"])
    op.create_index("ix_inventory_stock_movements_warehouse_id", "inventory_stock_movements", ["warehouse_id"])
    op.create_table("inventory_transfers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("transfer_number", sa.String(48), nullable=False),
        sa.Column("source_warehouse_id", sa.Integer(), sa.ForeignKey("inventory_warehouses.id"), nullable=False),
        sa.Column("destination_warehouse_id", sa.Integer(), sa.ForeignKey("inventory_warehouses.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("tracking_reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_inventory_transfers_organization_id", "inventory_transfers", ["organization_id"])
    op.create_index("uq_inventory_transfer_org_number", "inventory_transfers", ["organization_id","transfer_number"], unique=True)
    op.create_table("inventory_transfer_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("transfer_id", sa.Integer(), sa.ForeignKey("inventory_transfers.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(18,3), nullable=False))
    op.create_index("ix_inventory_transfer_lines_organization_id", "inventory_transfer_lines", ["organization_id"])
    op.create_index("ix_inventory_transfer_lines_transfer_id", "inventory_transfer_lines", ["transfer_id"])
    op.create_table("inventory_reservations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("inventory_warehouses.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False), sa.Column("source_reference", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Numeric(18,3), nullable=False), sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("idempotency_key", sa.String(100), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_inventory_reservations_organization_id", "inventory_reservations", ["organization_id"])
    op.create_index("ix_inventory_reservations_warehouse_id", "inventory_reservations", ["warehouse_id"])
    op.create_index("ix_inventory_reservations_product_id", "inventory_reservations", ["product_id"])
    op.create_index("ix_inventory_reservations_expires_at", "inventory_reservations", ["expires_at"])
    op.create_index("uq_inventory_reservation_org_idempotency", "inventory_reservations", ["organization_id","idempotency_key"], unique=True)
    op.create_table("inventory_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("inventory_warehouses.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("lot_number", sa.String(100), nullable=False, server_default=""),
        sa.Column("serial_number", sa.String(100), nullable=True),
        sa.Column("expiry_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quantity_on_hand", sa.Numeric(18,3), nullable=False, server_default="0"),
        sa.Column("unit_cost", sa.Numeric(18,4), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="available"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_inventory_batches_organization_id", "inventory_batches", ["organization_id"])
    op.create_index("ix_inventory_batches_warehouse_id", "inventory_batches", ["warehouse_id"])
    op.create_index("ix_inventory_batches_product_id", "inventory_batches", ["product_id"])
    op.create_index("ix_inventory_batches_expiry_date", "inventory_batches", ["expiry_date"])
    op.create_index("uq_inventory_batch_serial", "inventory_batches", ["organization_id","serial_number"], unique=True)
    op.create_table("inventory_stocktakes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("inventory_warehouses.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_inventory_stocktakes_organization_id", "inventory_stocktakes", ["organization_id"])
    op.create_index("ix_inventory_stocktakes_warehouse_id", "inventory_stocktakes", ["warehouse_id"])
    op.create_table("inventory_stocktake_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("stocktake_id", sa.Integer(), sa.ForeignKey("inventory_stocktakes.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("expected_quantity", sa.Numeric(18,3), nullable=False),
        sa.Column("counted_quantity", sa.Numeric(18,3), nullable=False))
    op.create_index("ix_inventory_stocktake_lines_organization_id", "inventory_stocktake_lines", ["organization_id"])
    op.create_index("ix_inventory_stocktake_lines_stocktake_id", "inventory_stocktake_lines", ["stocktake_id"])
    op.create_table("inventory_reorder_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("inventory_warehouses.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("minimum_quantity", sa.Numeric(18,3), nullable=False),
        sa.Column("maximum_quantity", sa.Numeric(18,3), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_index("ix_inventory_reorder_rules_organization_id", "inventory_reorder_rules", ["organization_id"])
    op.create_index("ix_inventory_reorder_rules_warehouse_id", "inventory_reorder_rules", ["warehouse_id"])
    op.create_index("ix_inventory_reorder_rules_product_id", "inventory_reorder_rules", ["product_id"])
    op.create_index("uq_inventory_reorder_rule", "inventory_reorder_rules", ["organization_id","warehouse_id","product_id"], unique=True)
    op.create_table("inventory_price_lists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True), sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_index("ix_inventory_price_lists_organization_id", "inventory_price_lists", ["organization_id"])
    op.create_index("ix_inventory_price_lists_branch_id", "inventory_price_lists", ["branch_id"])
    op.create_table("inventory_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("price_list_id", sa.Integer(), sa.ForeignKey("inventory_price_lists.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("unit_price", sa.Numeric(18,2), nullable=False),
        sa.Column("promotion_percent", sa.Numeric(7,4), nullable=False, server_default="0"))
    op.create_index("ix_inventory_prices_organization_id", "inventory_prices", ["organization_id"])
    op.create_index("ix_inventory_prices_price_list_id", "inventory_prices", ["price_list_id"])
    op.create_index("ix_inventory_prices_product_id", "inventory_prices", ["product_id"])
    op.create_index("uq_inventory_price_product", "inventory_prices", ["organization_id","price_list_id","product_id"], unique=True)


def downgrade():
    op.drop_index("ix_inventory_stock_movements_warehouse_id", table_name="inventory_stock_movements")
    with op.batch_alter_table("inventory_stock_movements") as batch_op:
        batch_op.drop_constraint("fk_inventory_movement_warehouse", type_="foreignkey")
        batch_op.drop_column("warehouse_id")
    op.drop_table("inventory_prices")
    op.drop_table("inventory_price_lists")
    op.drop_table("inventory_reorder_rules")
    op.drop_table("inventory_stocktake_lines")
    op.drop_table("inventory_stocktakes")
    op.drop_table("inventory_batches")
    op.drop_table("inventory_reservations")
    op.drop_table("inventory_transfer_lines")
    op.drop_table("inventory_transfers")
    op.drop_table("inventory_warehouses")

