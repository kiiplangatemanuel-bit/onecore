from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, ForeignKey, JSON, Text, Numeric, Index, CheckConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

def now():
    return datetime.now(timezone.utc)

class POSDevice(Base):
    __tablename__ = "pos_devices"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    device_key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(120))
    platform: Mapped[str] = mapped_column(String(40), default="browser")
    credential_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    offline_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[str] = mapped_column(String(24), default="never")
    last_sync_error: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    revoked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("uq_pos_device_org_key", "organization_id", "device_key", unique=True),)

class POSOfflineConflict(Base):
    __tablename__ = "pos_offline_conflicts"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("pos_devices.id"), index=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("pos_shifts.id"), index=True)
    client_transaction_id: Mapped[str] = mapped_column(String(100))
    conflict_type: Mapped[str] = mapped_column(String(40))
    server_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    client_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    resolution: Mapped[str] = mapped_column(String(32), default="")
    resolution_note: Mapped[str] = mapped_column(String(500), default="")
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("uq_pos_conflict_transaction", "organization_id", "device_id", "client_transaction_id", unique=True),)

class POSCustomer(Base):
    __tablename__ = "pos_customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    customer_number: Mapped[str] = mapped_column(String(40))
    full_name: Mapped[str] = mapped_column(String(180))
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    membership_tier: Mapped[str] = mapped_column(String(24), default="standard")
    points_balance: Mapped[int] = mapped_column(default=0)
    lifetime_spend: Mapped[Decimal] = mapped_column(Numeric(18,2), default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("uq_pos_customer_number", "organization_id", "customer_number", unique=True),
        Index("uq_pos_customer_phone", "organization_id", "phone", unique=True,
              postgresql_where=text("phone <> ''"), sqlite_where=text("phone <> ''")),
    )

class POSLoyaltyEntry(Base):
    __tablename__ = "pos_loyalty_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("pos_customers.id"), index=True)
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("pos_sales.id"), nullable=True, index=True)
    entry_type: Mapped[str] = mapped_column(String(16))
    points_delta: Mapped[int]
    idempotency_key: Mapped[str] = mapped_column(String(100))
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("uq_pos_loyalty_org_key", "organization_id", "idempotency_key", unique=True),)

class POSPeripheralCommand(Base):
    __tablename__ = "pos_peripheral_commands"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("pos_devices.id"), index=True)
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("pos_sales.id"), nullable=True)
    peripheral_type: Mapped[str] = mapped_column(String(20))
    command: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class POSCustomerSale(Base):
    __tablename__ = "pos_customer_sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("pos_customers.id"), index=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("pos_sales.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("uq_pos_customer_sale", "organization_id", "sale_id", unique=True),)


class POSLoyaltyRewardPolicy(Base):
    __tablename__ = "pos_loyalty_reward_policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    earn_points_per_100_units: Mapped[int] = mapped_column(default=1)
    points_per_currency_unit: Mapped[int] = mapped_column(default=100)
    max_redemption_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("50.00"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (
        Index("uq_pos_loyalty_reward_policy_org", "organization_id", unique=True),
        CheckConstraint("earn_points_per_100_units >= 0", name="ck_pos_loyalty_earn_rate_nonnegative"),
        CheckConstraint("points_per_currency_unit > 0", name="ck_pos_loyalty_points_per_unit_positive"),
        CheckConstraint("max_redemption_percent > 0 AND max_redemption_percent <= 100", name="ck_pos_loyalty_redemption_percent_range"),
    )
