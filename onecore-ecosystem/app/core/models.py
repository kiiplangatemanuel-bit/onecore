from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, ForeignKey, JSON, Text, Index, Numeric, Integer, BigInteger, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

def now():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(180), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    platform_role: Mapped[str] = mapped_column(String(40), default="customer")
    auth_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    supabase_auth_user_id: Mapped[str | None] = mapped_column(String(36), unique=True, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    industry: Mapped[str] = mapped_column(String(100), default="general")
    country: Mapped[str] = mapped_column(String(2), default="KE")
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    timezone: Mapped[str] = mapped_column(String(80), default="Africa/Nairobi")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Membership(Base):
    __tablename__ = "memberships"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    role: Mapped[str] = mapped_column(String(50), default="org_admin")
    branch_scope: Mapped[str] = mapped_column(String(500), default="*")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Record(Base):
    __tablename__ = "records"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    module_key: Mapped[str] = mapped_column(String(100), index=True)
    record_type: Mapped[str] = mapped_column(String(100), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    branch_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (Index("ix_record_tenant_module_type", "organization_id", "module_key", "record_type"),)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(nullable=True)
    action: Mapped[str] = mapped_column(String(120))
    resource_type: Mapped[str] = mapped_column(String(100), default="")
    resource_id: Mapped[str] = mapped_column(String(100), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CustomDomain(Base):
    __tablename__ = "custom_domains"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    hostname: Mapped[str] = mapped_column(String(253), unique=True, index=True)
    verification_token: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="pending_verification")
    tls_status: Mapped[str] = mapped_column(String(30), default="not_provisioned")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class SystemNotice(Base):
    __tablename__ = "system_notices"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(180))
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), default="info")
    audience: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class NoticeDismissal(Base):
    __tablename__ = "notice_dismissals"
    id: Mapped[int] = mapped_column(primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("system_notices.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    dismissed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_notice_dismissal_user_notice", "user_id", "notice_id", unique=True),)


class OrganizationInvitation(Base):
    __tablename__ = "organization_invitations"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(50))
    branch_scope: Mapped[str] = mapped_column(String(500), default="*")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Branch(Base):
    __tablename__ = "branches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(180))
    address: Mapped[str] = mapped_column(String(500), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_branch_org_code", "organization_id", "code", unique=True),)


class InventoryProduct(Base):
    """Tenant-owned inventory item; SKU uniqueness is enforced per organization."""
    __tablename__ = "inventory_products"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    sku: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str] = mapped_column(String(24), default="unit")
    sale_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    cost_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_inventory_product_org_sku", "organization_id", "sku", unique=True),)


class InventoryStockMovement(Base):
    """Append-only stock ledger. Positive deltas receive stock; negative deltas issue it."""
    __tablename__ = "inventory_stock_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_products.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_warehouses.id"), nullable=True, index=True)
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    movement_type: Mapped[str] = mapped_column(String(20))
    reference: Mapped[str] = mapped_column(String(120), default="")
    idempotency_key: Mapped[str] = mapped_column(String(100))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("ix_inventory_movement_org_idempotency", "organization_id", "idempotency_key", unique=True),
        Index("ix_inventory_movement_org_product_branch", "organization_id", "product_id", "branch_id"),
    )


class AccountingAccount(Base):
    """Tenant-owned chart-of-accounts entry."""
    __tablename__ = "accounting_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(180))
    account_type: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_accounting_account_org_code", "organization_id", "code", unique=True),)


class AccountingJournal(Base):
    """Journal header. Posted entries are immutable through the application API."""
    __tablename__ = "accounting_journals"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    journal_number: Mapped[str] = mapped_column(String(40))
    reference: Mapped[str] = mapped_column(String(120), default="")
    memo: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    entry_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    posted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_accounting_journal_org_number", "organization_id", "journal_number", unique=True),)


class AccountingJournalLine(Base):
    """Debit/credit line belonging to one tenant journal."""
    __tablename__ = "accounting_journal_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("accounting_journals.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    description: Mapped[str] = mapped_column(String(240), default="")
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CRMContact(Base):
    """Organization-owned customer/prospect contact."""
    __tablename__ = "crm_contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(180))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    company: Mapped[str] = mapped_column(String(180), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("ix_crm_contact_org_email", "organization_id", "email"),
        Index("ix_crm_contact_org_phone", "organization_id", "phone"),
    )


class CRMLead(Base):
    """Tenant-owned lead and sales pipeline opportunity."""
    __tablename__ = "crm_leads"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("crm_contacts.id"), nullable=True, index=True)
    source_campaign_id: Mapped[int | None] = mapped_column(ForeignKey("crm_campaigns.id", name="fk_crm_lead_source_campaign"), nullable=True)
    title: Mapped[str] = mapped_column(String(180))
    source: Mapped[str] = mapped_column(String(60), default="other")
    stage: Mapped[str] = mapped_column(String(24), default="new")
    estimated_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    next_step: Mapped[str] = mapped_column(String(500), default="")
    expected_close_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    probability_override: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    actual_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (Index("ix_crm_lead_org_stage", "organization_id", "stage"), Index("ix_crm_lead_source_campaign", "organization_id", "source_campaign_id"))


class CRMActivity(Base):
    """Auditable sales activity linked to a tenant contact or lead."""
    __tablename__ = "crm_activities"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("crm_contacts.id"), nullable=True, index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("crm_leads.id"), nullable=True, index=True)
    activity_type: Mapped[str] = mapped_column(String(24))
    subject: Mapped[str] = mapped_column(String(180))
    notes: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProcurementSupplier(Base):
    __tablename__ = "procurement_suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tax_pin: Mapped[str] = mapped_column(String(24), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_procurement_supplier_org_name", "organization_id", "name"),)


class ProcurementPurchaseOrder(Base):
    __tablename__ = "procurement_purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("procurement_suppliers.id"), index=True)
    order_number: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    notes: Mapped[str] = mapped_column(String(1000), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_procurement_po_org_number", "organization_id", "order_number", unique=True),)


class ProcurementPurchaseOrderLine(Base):
    __tablename__ = "procurement_purchase_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("procurement_purchase_orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_products.id"), index=True)
    quantity_ordered: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=Decimal("0"))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class POSShift(Base):
    __tablename__ = "pos_shifts"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    cashier_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("pos_devices.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="open")
    opening_cash: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    closing_cash: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_cash: Mapped[Decimal | None] = mapped_column(Numeric(18,2), nullable=True)
    counted_cash: Mapped[Decimal | None] = mapped_column(Numeric(18,2), nullable=True)
    cash_variance: Mapped[Decimal | None] = mapped_column(Numeric(18,2), nullable=True)
    reconciliation_status: Mapped[str] = mapped_column(String(20), default="open")
    counted_denominations: Mapped[dict] = mapped_column(JSON, default=dict)
    close_note: Mapped[str] = mapped_column(String(500), default="")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str] = mapped_column(String(500), default="")
    __table_args__ = (Index("uq_pos_shift_open_device", "organization_id", "device_id", unique=True,
        postgresql_where=text("status = 'open' AND device_id IS NOT NULL"),
        sqlite_where=text("status = 'open' AND device_id IS NOT NULL")),)


class POSCashMovement(Base):
    __tablename__ = "pos_cash_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("pos_shifts.id"), index=True)
    movement_type: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(18,2))
    reason: Mapped[str] = mapped_column(String(500))
    reference: Mapped[str] = mapped_column(String(120), default="")
    idempotency_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default="recorded")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    authorized_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_pos_cash_movement_org_key","organization_id","idempotency_key",unique=True),
        Index("ix_pos_cash_movement_shift","organization_id","shift_id","status"))


class POSSale(Base):
    __tablename__ = "pos_sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("pos_shifts.id"), index=True)
    cashier_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    client_transaction_id: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    loyalty_points_redeemed: Mapped[int] = mapped_column(default=0)
    loyalty_discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    status: Mapped[str] = mapped_column(String(16), default="posted")
    offline_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_pos_sale_org_client_txn", "organization_id", "client_transaction_id", unique=True),)


class POSSaleLine(Base):
    __tablename__ = "pos_sale_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("pos_sales.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_products.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    loyalty_discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class POSPayment(Base):
    __tablename__ = "pos_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("pos_sales.id"), index=True)
    method: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    provider_reference: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(16), default="recorded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class POSReturn(Base):
    __tablename__ = "pos_returns"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("pos_sales.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    client_return_id: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(500))
    refund_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_pos_return_org_client_id", "organization_id", "client_return_id", unique=True),)


class POSReturnLine(Base):
    __tablename__ = "pos_return_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    return_id: Mapped[int] = mapped_column(ForeignKey("pos_returns.id"), index=True)
    sale_line_id: Mapped[int] = mapped_column(ForeignKey("pos_sale_lines.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_products.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class POSRefund(Base):
    __tablename__ = "pos_refunds"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    return_id: Mapped[int] = mapped_column(ForeignKey("pos_returns.id"), index=True)
    method: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    provider_reference: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(16), default="recorded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SchoolClass(Base):
    __tablename__ = "school_classes"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    stream: Mapped[str] = mapped_column(String(40), default="")
    academic_year: Mapped[int] = mapped_column()
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_school_class_org_year_name_stream", "organization_id", "academic_year", "name", "stream", unique=True),)


class SchoolLearner(Base):
    __tablename__ = "school_learners"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    class_id: Mapped[int | None] = mapped_column(ForeignKey("school_classes.id"), nullable=True, index=True)
    admission_number: Mapped[str] = mapped_column(String(40))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    date_of_birth: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    guardian_name: Mapped[str] = mapped_column(String(180), default="")
    guardian_phone: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(20), default="applicant")
    admitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_school_learner_org_admission", "organization_id", "admission_number", unique=True),)


class SchoolSubject(Base):
    __tablename__ = "school_subjects"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    code: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_school_subject_org_code", "organization_id", "code", unique=True),)


class SchoolAssessment(Base):
    __tablename__ = "school_assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("school_classes.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("school_subjects.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    academic_year: Mapped[int] = mapped_column()
    term: Mapped[str] = mapped_column(String(24))
    maximum_score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    weight: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("1"))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    published_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SchoolMark(Base):
    __tablename__ = "school_marks"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("school_assessments.id"), index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("school_learners.id"), index=True)
    score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    entered_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (Index("ix_school_mark_org_assessment_learner", "organization_id", "assessment_id", "learner_id", unique=True),)


class SchoolGradeBand(Base):
    __tablename__ = "school_grade_bands"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    scale_name: Mapped[str] = mapped_column(String(80), default="default")
    grade: Mapped[str] = mapped_column(String(12))
    minimum_percent: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    maximum_percent: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    points: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=Decimal("0"))
    __table_args__ = (Index("ix_school_grade_org_scale_grade", "organization_id", "scale_name", "grade", unique=True),)


class AccountingInvoice(Base):
    """Tenant-owned AR/AP invoice; posted invoice lines are immutable."""
    __tablename__ = "accounting_invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    invoice_type: Mapped[str] = mapped_column(String(12))  # receivable or payable
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("crm_contacts.id"), nullable=True, index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("procurement_suppliers.id"), nullable=True, index=True)
    crm_sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("crm_sales_orders.id"), nullable=True)
    invoice_number: Mapped[str] = mapped_column(String(60))
    issue_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    control_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    journal_id: Mapped[int | None] = mapped_column(ForeignKey("accounting_journals.id"), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    posted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("ix_accounting_invoice_org_number", "organization_id", "invoice_number", unique=True),
        Index("ix_accounting_invoice_org_status_due", "organization_id", "status", "due_date"),
        Index("ix_accounting_invoice_org_crm_order", "organization_id", "crm_sales_order_id"),
    )


class AccountingInvoiceLine(Base):
    __tablename__ = "accounting_invoice_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("accounting_invoices.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    tax_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounting_accounts.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(240))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AccountingInvoicePayment(Base):
    __tablename__ = "accounting_invoice_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("accounting_invoices.id"), index=True)
    payment_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    journal_id: Mapped[int] = mapped_column(ForeignKey("accounting_journals.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    payment_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reference: Mapped[str] = mapped_column(String(120), default="")
    idempotency_key: Mapped[str] = mapped_column(String(100))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("ix_accounting_invoice_payment_org_idempotency", "organization_id", "idempotency_key", unique=True),
    )


class AccountingInvoiceApproval(Base):
    __tablename__ = "accounting_invoice_approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("accounting_invoices.id"), index=True)
    submitted_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    approver_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    decision_note: Mapped[str] = mapped_column(String(500), default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (Index("ix_accounting_invoice_approval_org_invoice", "organization_id", "invoice_id", unique=True),)


class AccountingCreditNote(Base):
    __tablename__ = "accounting_credit_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("accounting_invoices.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    credit_note_number: Mapped[str] = mapped_column(String(60))
    issue_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(500))
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    journal_id: Mapped[int | None] = mapped_column(ForeignKey("accounting_journals.id"), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    posted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("ix_accounting_credit_note_org_number", "organization_id", "credit_note_number", unique=True),
        Index("ix_accounting_credit_note_org_key", "organization_id", "idempotency_key", unique=True),
    )


class AccountingCreditNoteLine(Base):
    __tablename__ = "accounting_credit_note_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    credit_note_id: Mapped[int] = mapped_column(ForeignKey("accounting_credit_notes.id"), index=True)
    invoice_line_id: Mapped[int] = mapped_column(ForeignKey("accounting_invoice_lines.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AccountingFiscalPeriod(Base):
    __tablename__ = "accounting_fiscal_periods"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(12), default="open")
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_accounting_period_org_code", "organization_id", "code", unique=True),)


class AccountingBudget(Base):
    __tablename__ = "accounting_budgets"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    fiscal_period_id: Mapped[int] = mapped_column(ForeignKey("accounting_fiscal_periods.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AccountingBudgetLine(Base):
    __tablename__ = "accounting_budget_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("accounting_budgets.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AccountingFixedAsset(Base):
    __tablename__ = "accounting_fixed_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    asset_code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(180))
    acquisition_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cost: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    salvage_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    useful_life_months: Mapped[int] = mapped_column()
    accumulated_depreciation: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    asset_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    accumulated_depreciation_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    depreciation_expense_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_accounting_fixed_asset_org_code", "organization_id", "asset_code", unique=True),)


class AccountingDepreciationEntry(Base):
    __tablename__ = "accounting_depreciation_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("accounting_fixed_assets.id"), index=True)
    period_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    journal_id: Mapped[int] = mapped_column(ForeignKey("accounting_journals.id"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("ix_accounting_depreciation_org_key", "organization_id", "idempotency_key", unique=True),
        Index("ix_accounting_depreciation_asset_period", "organization_id", "asset_id", "period_date", unique=True),
    )


class AccountingBankStatement(Base):
    __tablename__ = "accounting_bank_statements"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    bank_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    statement_reference: Mapped[str] = mapped_column(String(80))
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    closing_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    reconciled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_accounting_bank_statement_org_ref", "organization_id", "statement_reference", unique=True),)


class AccountingBankStatementLine(Base):
    __tablename__ = "accounting_bank_statement_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey("accounting_bank_statements.id"), index=True)
    line_number: Mapped[int] = mapped_column()
    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    description: Mapped[str] = mapped_column(String(240))
    reference: Mapped[str] = mapped_column(String(120), default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    matched_journal_line_id: Mapped[int | None] = mapped_column(ForeignKey("accounting_journal_lines.id"), nullable=True)
    matched_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("ix_accounting_bank_statement_line_number", "statement_id", "line_number", unique=True),
        Index("ix_accounting_bank_match_org_journal", "organization_id", "matched_journal_line_id", unique=True),
    )


class CRMQuote(Base):
    __tablename__ = "crm_quotes"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("crm_contacts.id"), index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("crm_leads.id"), nullable=True, index=True)
    quote_number: Mapped[str] = mapped_column(String(60))
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    issue_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_crm_quote_org_number", "organization_id", "quote_number", unique=True),)


class CRMQuoteLine(Base):
    __tablename__ = "crm_quote_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("crm_quotes.id"), index=True)
    description: Mapped[str] = mapped_column(String(240))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CRMSalesOrder(Base):
    __tablename__ = "crm_sales_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("crm_quotes.id"), unique=True, index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("crm_contacts.id"), index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("crm_leads.id"), nullable=True, index=True)
    order_number: Mapped[str] = mapped_column(String(60))
    currency: Mapped[str] = mapped_column(String(3))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("ix_crm_sales_order_org_number", "organization_id", "order_number", unique=True),
    )


class CRMSalesOrderLine(Base):
    __tablename__ = "crm_sales_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("crm_sales_orders.id"), index=True)
    quote_line_id: Mapped[int] = mapped_column(ForeignKey("crm_quote_lines.id"), index=True)
    description: Mapped[str] = mapped_column(String(240))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CRMContactConsent(Base):
    """Append-only evidence of a contact's channel-specific marketing consent."""
    __tablename__ = "crm_contact_consents"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("crm_contacts.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(String(24), default="marketing")
    decision: Mapped[str] = mapped_column(String(12))
    source: Mapped[str] = mapped_column(String(80))
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        Index("ix_crm_consent_org_contact_channel", "organization_id", "contact_id", "channel", "purpose", "id"),
    )


class CRMCampaign(Base):
    __tablename__ = "crm_campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    campaign_number: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(180))
    subject: Mapped[str] = mapped_column(String(240), default="")
    channel: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(String(24), default="marketing")
    message: Mapped[str] = mapped_column(Text)
    budget_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    budget_currency: Mapped[str] = mapped_column(String(3), default="KES")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("ix_crm_campaign_org_number", "organization_id", "campaign_number", unique=True),
    )


class CRMCampaignRecipient(Base):
    __tablename__ = "crm_campaign_recipients"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("crm_campaigns.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("crm_contacts.id"), index=True)
    consent_id: Mapped[int] = mapped_column(ForeignKey("crm_contact_consents.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    address_snapshot: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(16), default="prepared")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subject_snapshot: Mapped[str | None] = mapped_column(String(240), nullable=True)
    message_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("ix_crm_campaign_recipient_unique", "campaign_id", "contact_id", unique=True),
    )


class SchoolEnrollmentHistory(Base):
    """Append-only record of each learner's class placement change."""
    __tablename__ = "school_enrollment_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("school_learners.id"), index=True)
    from_class_id: Mapped[int] = mapped_column(ForeignKey("school_classes.id"), index=True)
    to_class_id: Mapped[int] = mapped_column(ForeignKey("school_classes.id"), index=True)
    effective_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    change_type: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(500))
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SchoolAttendance(Base):
    """One daily attendance decision per learner and tenant."""
    __tablename__ = "school_attendance"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("school_classes.id"), index=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("school_learners.id"), index=True)
    attendance_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(String(500), default="")
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_school_attendance_org_date_learner", "organization_id", "attendance_date", "learner_id", unique=True),)


class ProcurementRequisition(Base):
    __tablename__ = "procurement_requisitions"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    requisition_number: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    justification: Mapped[str] = mapped_column(String(1000))
    rejection_reason: Mapped[str] = mapped_column(String(500), default="")
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_procurement_req_org_number", "organization_id", "requisition_number", unique=True),)


class ProcurementRequisitionLine(Base):
    __tablename__ = "procurement_requisition_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    requisition_id: Mapped[int] = mapped_column(ForeignKey("procurement_requisitions.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_products.id"), index=True)
    quantity_requested: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProcurementGoodsReceipt(Base):
    __tablename__ = "procurement_goods_receipts"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("procurement_purchase_orders.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    receipt_number: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default="pending_inspection")
    received_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    inspected_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    inspected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inspection_note: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_procurement_grn_org_number", "organization_id", "receipt_number", unique=True),)


class ProcurementGoodsReceiptLine(Base):
    __tablename__ = "procurement_goods_receipt_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    goods_receipt_id: Mapped[int] = mapped_column(ForeignKey("procurement_goods_receipts.id"), index=True)
    purchase_order_line_id: Mapped[int] = mapped_column(ForeignKey("procurement_purchase_order_lines.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_products.id"), index=True)
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    quantity_accepted: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=Decimal("0"))
    quantity_rejected: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=Decimal("0"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    rejection_reason: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("ix_procurement_grn_line_org_key", "organization_id", "idempotency_key", unique=True),
    )


class ProcurementApprovalRule(Base):
    __tablename__ = "procurement_approval_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    minimum_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    maximum_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    approval_level: Mapped[int] = mapped_column()
    approver_role: Mapped[str] = mapped_column(String(40), default="org_admin")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_procurement_approval_rule_org_level", "organization_id", "approval_level", unique=True),)


class ProcurementApprovalAction(Base):
    __tablename__ = "procurement_approval_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(24))
    entity_id: Mapped[int] = mapped_column()
    approval_level: Mapped[int] = mapped_column()
    approver_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_procurement_approval_action_org_entity_level", "organization_id", "entity_type", "entity_id", "approval_level", unique=True),)


class ProcurementRFQ(Base):
    __tablename__ = "procurement_rfqs"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    rfq_number: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="open")
    closing_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(String(1000), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_procurement_rfq_org_number", "organization_id", "rfq_number", unique=True),)


class ProcurementRFQLine(Base):
    __tablename__ = "procurement_rfq_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("procurement_rfqs.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_products.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProcurementRFQInvitation(Base):
    __tablename__ = "procurement_rfq_invitations"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("procurement_rfqs.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("procurement_suppliers.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="invited")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_procurement_rfq_invitation_unique", "rfq_id", "supplier_id", unique=True),)


class ProcurementRFQQuote(Base):
    __tablename__ = "procurement_rfq_quotes"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("procurement_rfqs.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("procurement_suppliers.id"), index=True)
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    delivery_days: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), default="submitted")
    submitted_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_procurement_rfq_quote_supplier", "organization_id", "rfq_id", "supplier_id", unique=True),)


class ProcurementRFQQuoteLine(Base):
    __tablename__ = "procurement_rfq_quote_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("procurement_rfq_quotes.id"), index=True)
    rfq_line_id: Mapped[int] = mapped_column(ForeignKey("procurement_rfq_lines.id"), index=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProcurementSupplierInvoice(Base):
    __tablename__ = "procurement_supplier_invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("procurement_suppliers.id"), index=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("procurement_purchase_orders.id"), index=True)
    invoice_number: Mapped[str] = mapped_column(String(80))
    invoice_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    status: Mapped[str] = mapped_column(String(20), default="pending_match")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    matched_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_procurement_invoice_org_supplier_number", "organization_id", "supplier_id", "invoice_number", unique=True),)


class ProcurementSupplierInvoiceLine(Base):
    __tablename__ = "procurement_supplier_invoice_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("procurement_supplier_invoices.id"), index=True)
    purchase_order_line_id: Mapped[int] = mapped_column(ForeignKey("procurement_purchase_order_lines.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProcurementSupplierReturn(Base):
    __tablename__ = "procurement_supplier_returns"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    goods_receipt_id: Mapped[int] = mapped_column(ForeignKey("procurement_goods_receipts.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("procurement_suppliers.id"), index=True)
    return_number: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="posted")
    reason: Mapped[str] = mapped_column(String(500))
    credit_note_reference: Mapped[str] = mapped_column(String(100), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_procurement_return_org_number", "organization_id", "return_number", unique=True),)


class ProcurementSupplierReturnLine(Base):
    __tablename__ = "procurement_supplier_return_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    return_id: Mapped[int] = mapped_column(ForeignKey("procurement_supplier_returns.id"), index=True)
    receipt_line_id: Mapped[int] = mapped_column(ForeignKey("procurement_goods_receipt_lines.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AccountingRefund(Base):
    """Cash refund against a posted credit note; immutable after posting."""
    __tablename__ = "accounting_refunds"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("accounting_invoices.id"), index=True)
    credit_note_id: Mapped[int] = mapped_column(ForeignKey("accounting_credit_notes.id"), index=True)
    payment_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    journal_id: Mapped[int] = mapped_column(ForeignKey("accounting_journals.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    refund_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reference: Mapped[str] = mapped_column(String(120), default="")
    idempotency_key: Mapped[str] = mapped_column(String(100))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("ix_accounting_refund_org_key", "organization_id", "idempotency_key", unique=True),
    )


class AccountingProcurementLink(Base):
    """Idempotent bridge from a three-way-matched procurement bill to the AP ledger."""
    __tablename__ = "accounting_procurement_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    procurement_invoice_id: Mapped[int] = mapped_column(ForeignKey("procurement_supplier_invoices.id"), index=True)
    accounting_invoice_id: Mapped[int] = mapped_column(ForeignKey("accounting_invoices.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("ix_accounting_procurement_link_org_source", "organization_id", "procurement_invoice_id", unique=True),
        Index("ix_accounting_procurement_link_org_ledger", "organization_id", "accounting_invoice_id", unique=True),
    )


class POSAccountingMapping(Base):
    """Tenant-level ledger accounts used for automatic POS journal posting."""
    __tablename__ = "pos_accounting_mappings"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), unique=True, index=True)
    cash_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    card_clearing_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    bank_clearing_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    credit_receivable_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    sales_revenue_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    sales_discount_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    output_tax_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounting_accounts.id"), nullable=True)
    sales_returns_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class POSAccountingLink(Base):
    """Unique source-to-journal bridge; pending links are safely retryable."""
    __tablename__ = "pos_accounting_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[int] = mapped_column()
    journal_id: Mapped[int | None] = mapped_column(ForeignKey("accounting_journals.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    failure_reason: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        Index("ix_pos_accounting_source", "organization_id", "source_type", "source_id", unique=True),
        Index("ix_pos_accounting_pending", "organization_id", "status"),
    )



class MpesaPaymentIntent(Base):
    __tablename__ = "mpesa_payment_intents"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("pos_payments.id"), unique=True)
    phone_number: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    checkout_request_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    merchant_request_id: Mapped[str] = mapped_column(String(100), default="")
    callback_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="initiating")
    result_code: Mapped[str] = mapped_column(String(40), default="")
    result_description: Mapped[str] = mapped_column(String(500), default="")
    mpesa_receipt_number: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MpesaRefundIntent(Base):
    __tablename__ = "mpesa_refund_intents"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    refund_id: Mapped[int] = mapped_column(ForeignKey("pos_refunds.id"), unique=True, index=True)
    phone_number: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    conversation_id: Mapped[str] = mapped_column(String(100), default="")
    originator_conversation_id: Mapped[str] = mapped_column(String(100), default="")
    callback_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="initiating")
    result_code: Mapped[str] = mapped_column(String(40), default="")
    result_description: Mapped[str] = mapped_column(String(500), default="")
    mpesa_receipt_number: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CRMCampaignDelivery(Base):
    """Append-only provider attempt and unsubscribe evidence for a campaign recipient."""
    __tablename__ = "crm_campaign_deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("crm_campaign_recipients.id"), index=True)
    attempt_number: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(16))
    provider_message_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    unsubscribe_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CRMCommunicationTemplate(Base):
    __tablename__ = "crm_communication_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id", name="fk_crm_template_branch"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    version: Mapped[int] = mapped_column(default=1)
    channel: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(String(24), default="marketing")
    subject: Mapped[str] = mapped_column(String(240), default="")
    body: Mapped[str] = mapped_column(Text)
    variables: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (Index("ix_crm_template_org_name_version", "organization_id", "name", "version", unique=True),)

class CRMAudienceSegment(Base):
    __tablename__ = "crm_audience_segments"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id", name="fk_crm_segment_branch"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(String(500), default="")
    rules: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (Index("ix_crm_segment_org_name", "organization_id", "name", unique=True),)

class CRMCampaignSchedule(Base):
    __tablename__ = "crm_campaign_schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("crm_campaigns.id"), index=True, unique=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    timezone_name: Mapped[str] = mapped_column(String(80), default="Africa/Nairobi")
    recurrence: Mapped[str] = mapped_column(String(12), default="once")
    template_id: Mapped[int | None] = mapped_column(ForeignKey("crm_communication_templates.id"), nullable=True)
    segment_id: Mapped[int | None] = mapped_column(ForeignKey("crm_audience_segments.id"), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_count: Mapped[int] = mapped_column(default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_campaign_id: Mapped[int | None] = mapped_column(ForeignKey("crm_campaigns.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(String(1000), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class HealthcarePatient(Base):
    __tablename__ = "healthcare_patients"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    medical_record_number: Mapped[str] = mapped_column(String(60))
    encrypted_profile: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (Index("ix_health_patient_org_mrn", "organization_id", "medical_record_number", unique=True),)

class HealthcareEncounter(Base):
    __tablename__ = "healthcare_encounters"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("healthcare_patients.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    encounter_type: Mapped[str] = mapped_column(String(32))
    encrypted_clinical_note: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")
    clinician_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class HealthcarePatientAccess(Base):
    __tablename__ = "healthcare_patient_access"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("healthcare_patients.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    access_level: Mapped[str] = mapped_column(String(16), default="read")
    granted_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_health_access_patient_user", "organization_id", "patient_id", "user_id"),)

class HealthcareConsent(Base):
    __tablename__ = "healthcare_consents"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("healthcare_patients.id"), index=True)
    consent_type: Mapped[str] = mapped_column(String(40))
    decision: Mapped[str] = mapped_column(String(16))
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str] = mapped_column(String(500), default="")
    evidence_reference: Mapped[str] = mapped_column(String(180), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class HealthcareAccessAudit(Base):
    __tablename__ = "healthcare_access_audits"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("healthcare_patients.id"), index=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(String(500), default="")
    emergency: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class HealthcareRoleAssignment(Base):
    __tablename__ = "healthcare_role_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    scope_key: Mapped[str] = mapped_column(String(36), default="*")
    role: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    assigned_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_healthcare_role_org_user_scope", "organization_id", "user_id", "scope_key", "role", unique=True),)


class HealthcareBreakGlassSession(Base):
    __tablename__ = "healthcare_break_glass_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("healthcare_patients.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    justification: Mapped[str] = mapped_column(String(1000))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HealthcareAppointment(Base):
    __tablename__ = "healthcare_appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("healthcare_patients.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    provider_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CRMForecastSetting(Base):
    __tablename__ = "crm_forecast_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), unique=True, index=True)
    stage_probabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    scenario_multipliers: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class CRMSalesTarget(Base):
    __tablename__ = "crm_sales_targets"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    period_type: Mapped[str] = mapped_column(String(12))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rep_key: Mapped[str] = mapped_column(String(32), default="team")
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (Index("ix_crm_target_org_period_rep_currency", "organization_id", "period_type", "period_start", "rep_key", "currency", unique=True),)

class CRMForecastSnapshot(Base):
    __tablename__ = "crm_forecast_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    period_type: Mapped[str] = mapped_column(String(12))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rep_key: Mapped[str] = mapped_column(String(32), default="team")
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    scenario: Mapped[str] = mapped_column(String(16))
    forecast_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    opportunity_count: Mapped[int] = mapped_column(default=0)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    snapshot_by: Mapped[int] = mapped_column(ForeignKey("users.id"))

class CRMCampaignAttribution(Base):
    __tablename__ = "crm_campaign_attributions"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("crm_campaigns.id"))
    contact_id: Mapped[int] = mapped_column(ForeignKey("crm_contacts.id"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("crm_leads.id"), nullable=True)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("crm_sales_orders.id"), nullable=True)
    accounting_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("accounting_invoices.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(20))
    revenue_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (Index("ix_crm_attribution_org_idempotency", "organization_id", "idempotency_key", unique=True),
                      Index("uq_crm_attribution_org_invoice", "organization_id", "accounting_invoice_id", unique=True))

class CRMWorkerHeartbeat(Base):
    __tablename__ = "crm_worker_heartbeats"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    worker_name: Mapped[str] = mapped_column(String(80))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_processed: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str] = mapped_column(String(500), default="")
    __table_args__ = (Index("ix_crm_worker_org_name", "organization_id", "worker_name", unique=True),)


class HealthcareResource(Base):
    """Tenant- and branch-scoped hospital workflow record; clinical payloads are encrypted."""
    __tablename__ = "healthcare_resources"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("healthcare_patients.id"), nullable=True, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("healthcare_resources.id"), nullable=True, index=True)
    resource_type: Mapped[str] = mapped_column(String(40), index=True)
    external_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    encrypted_payload: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (
        Index("ix_health_resource_org_type_external", "organization_id", "resource_type", "external_key", unique=True),
        Index("ix_health_resource_org_type_idem", "organization_id", "resource_type", "idempotency_key", unique=True),
        Index("ix_health_resource_org_patient_type", "organization_id", "patient_id", "resource_type"),
    )


class HealthcareEvent(Base):
    """Append-only clinical and patient-movement event ledger."""
    __tablename__ = "healthcare_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("healthcare_patients.id"), index=True)
    resource_id: Mapped[int | None] = mapped_column(ForeignKey("healthcare_resources.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(60))
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    encrypted_detail: Mapped[str] = mapped_column(Text)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("ix_health_event_org_idempotency", "organization_id", "idempotency_key", unique=True),
        Index("ix_health_event_patient_time", "organization_id", "patient_id", "occurred_at"),
    )

class SupportTicket(Base):
    __tablename__ = "support_tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    subject: Mapped[str] = mapped_column(String(180))
    category: Mapped[str] = mapped_column(String(40), default="general")
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    contact_name: Mapped[str] = mapped_column(String(180))
    contact_email: Mapped[str] = mapped_column(String(320), index=True)
    contact_phone: Mapped[str] = mapped_column(String(32), default="")
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    assigned_to_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    guest_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (Index("uq_support_ticket_guest_token_hash", "guest_token_hash", unique=True),)


class SupportMessage(Base):
    __tablename__ = "support_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("support_tickets.id", ondelete="CASCADE"), index=True)
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    author_name: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_support_message_ticket_created", "ticket_id", "created_at"),)

class EmailVerification(Base):
    __tablename__ = "email_verifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)



class PasswordResetToken(Base):
    """Hashed, short-lived, single-use password recovery token."""
    __tablename__ = "password_reset_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PortalAuthorizationCode(Base):
    """Single-use PKCE authorization code for secure cross-origin portal sign-in."""
    __tablename__ = "portal_authorization_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    redirect_uri: Mapped[str] = mapped_column(String(2048))
    code_challenge: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PortalWorkflowRecord(Base):
    """Typed, tenant-scoped records backing authenticated public-portal workflows.

    Sensitive records (security reports and applicant records) are always owner-scoped.
    Organization records are always filtered through an active membership in the API.
    """
    __tablename__ = "portal_workflow_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    portal_key: Mapped[str] = mapped_column(String(24), index=True)
    record_type: Mapped[str] = mapped_column(String(48), index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    visibility: Mapped[str] = mapped_column(String(16), default="private")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (
        Index("ix_portal_workflow_org_portal_type", "organization_id", "portal_key", "record_type"),
        Index("ix_portal_workflow_owner_portal_type", "owner_user_id", "portal_key", "record_type"),
        Index("ix_portal_workflow_public", "portal_key", "record_type", "visibility", "status"),
    )


class UserMFAFactor(Base):
    """Encrypted TOTP seed and replay-prevention state for one account."""
    __tablename__ = "user_mfa_factors"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    secret_ciphertext: Mapped[str] = mapped_column(String(512))
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pending_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class MFARecoveryCode(Base):
    """Single-use recovery code stored only as a digest."""
    __tablename__ = "mfa_recovery_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MFAChallenge(Base):
    """Short-lived, single-use second-factor challenge issued after password verification."""
    __tablename__ = "mfa_challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    auth_version: Mapped[int] = mapped_column(Integer)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class SupportAttachment(Base):
    """Private object-storage metadata for a support ticket attachment."""
    __tablename__ = "support_attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("support_tickets.id", ondelete="CASCADE"), index=True)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    content_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    scan_engine: Mapped[str | None] = mapped_column(String(40), nullable=True)
    scan_result: Mapped[str | None] = mapped_column(String(24), nullable=True)
    scan_signature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DeveloperApiKey(Base):
    """Hashed organization API credential; plaintext is returned only once at issuance."""
    __tablename__ = "developer_api_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    key_prefix: Mapped[str] = mapped_column(String(24), unique=True)
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    environment: Mapped[str] = mapped_column(String(16), default="sandbox")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DeveloperApiKeyUsage(Base):
    """Auditable usage sample for requests authenticated with a developer API key."""
    __tablename__ = "developer_api_key_usages"
    id: Mapped[int] = mapped_column(primary_key=True)
    api_key_id: Mapped[int] = mapped_column(ForeignKey("developer_api_keys.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(String(255))
    method: Mapped[str] = mapped_column(String(10))
    status_code: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class DeveloperWebhookEndpoint(Base):
    """Private endpoint signing material for a developer webhook workflow record."""
    __tablename__ = "developer_webhook_endpoints"
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_record_id: Mapped[int] = mapped_column(ForeignKey("portal_workflow_records.id", ondelete="CASCADE"), unique=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    endpoint_url: Mapped[str] = mapped_column(String(2048))
    events: Mapped[list] = mapped_column(JSON, default=list)
    secret_encrypted: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    rotated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DeveloperWebhookDelivery(Base):
    """Durable, idempotent webhook outbox with bounded retry state."""
    __tablename__ = "developer_webhook_deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint_id: Mapped[int] = mapped_column(ForeignKey("developer_webhook_endpoints.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(String(80))
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (Index("uq_developer_webhook_endpoint_event", "endpoint_id", "event_id", unique=True),)


# Re-export the Status outbox model for existing model import conventions.
from app.core.models_status_alerts import StatusAlertDelivery  # noqa: E402,F401
