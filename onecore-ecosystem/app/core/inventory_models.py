"""Extended inventory and retail persistence models."""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class InventoryWarehouse(Base):
    __tablename__ = "inventory_warehouses"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(180))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (Index("uq_inventory_warehouse_org_code", "organization_id", "code", unique=True),)


class InventoryTransfer(Base):
    __tablename__ = "inventory_transfers"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    transfer_number: Mapped[str] = mapped_column(String(48))
    source_warehouse_id: Mapped[int] = mapped_column(ForeignKey("inventory_warehouses.id"))
    destination_warehouse_id: Mapped[int] = mapped_column(ForeignKey("inventory_warehouses.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    tracking_reference: Mapped[str] = mapped_column(String(120), default="")
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (Index("uq_inventory_transfer_org_number", "organization_id", "transfer_number", unique=True),)


class InventoryTransferLine(Base):
    __tablename__ = "inventory_transfer_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    transfer_id: Mapped[int] = mapped_column(ForeignKey("inventory_transfers.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_products.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))


class InventoryReservation(Base):
    __tablename__ = "inventory_reservations"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("inventory_warehouses.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_products.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(16))
    source_reference: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    status: Mapped[str] = mapped_column(String(16), default="active")
    idempotency_key: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (Index("uq_inventory_reservation_org_idempotency", "organization_id", "idempotency_key", unique=True),)


class InventoryBatch(Base):
    __tablename__ = "inventory_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("inventory_warehouses.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_products.id"), index=True)
    lot_number: Mapped[str] = mapped_column(String(100), default="")
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=Decimal("0"))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(16), default="available")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (Index("uq_inventory_batch_serial", "organization_id", "serial_number", unique=True),)


class InventoryStocktake(Base):
    __tablename__ = "inventory_stocktakes"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("inventory_warehouses.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    note: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class InventoryStocktakeLine(Base):
    __tablename__ = "inventory_stocktake_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    stocktake_id: Mapped[int] = mapped_column(ForeignKey("inventory_stocktakes.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_products.id"))
    expected_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    counted_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))


class InventoryReorderRule(Base):
    __tablename__ = "inventory_reorder_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("inventory_warehouses.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_products.id"), index=True)
    minimum_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    maximum_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    lead_time_days: Mapped[int] = mapped_column(Integer, default=7)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (Index("uq_inventory_reorder_rule", "organization_id", "warehouse_id", "product_id", unique=True),)


class InventoryPriceList(Base):
    __tablename__ = "inventory_price_lists"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class InventoryPrice(Base):
    __tablename__ = "inventory_prices"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    price_list_id: Mapped[int] = mapped_column(ForeignKey("inventory_price_lists.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_products.id"), index=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    promotion_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0"))
    __table_args__ = (Index("uq_inventory_price_product", "organization_id", "price_list_id", "product_id", unique=True),)

class InventoryReplenishmentRun(Base):
    __tablename__ = "inventory_replenishment_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    requisition_id: Mapped[int] = mapped_column(ForeignKey("procurement_requisitions.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (Index("uq_inventory_replenishment_org_key_branch", "organization_id", "idempotency_key", "branch_id", unique=True),)
