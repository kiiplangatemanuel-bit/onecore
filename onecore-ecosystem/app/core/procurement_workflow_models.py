from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, DateTime, ForeignKey, Numeric, JSON, Index, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

def now():
    return datetime.now(timezone.utc)

class ProcurementSettlement(Base):
    __tablename__ = "procurement_settlements"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("procurement_suppliers.id"), index=True)
    payment_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    provider: Mapped[str] = mapped_column(String(24), default="manual")
    provider_reference: Mapped[str] = mapped_column(String(120), default="")
    provider_phone_number: Mapped[str] = mapped_column(String(16), default="")
    callback_token_hash: Mapped[str] = mapped_column(String(64), default="")
    provider_conversation_id: Mapped[str] = mapped_column(String(100), default="")
    provider_originator_id: Mapped[str] = mapped_column(String(100), default="")
    provider_result_code: Mapped[str] = mapped_column(String(40), default="")
    provider_result_description: Mapped[str] = mapped_column(String(500), default="")
    reference: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(24), default="pending_verification")
    payment_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    journal_id: Mapped[int | None] = mapped_column(ForeignKey("accounting_journals.id"), nullable=True)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_procurement_settlement_org_key", "organization_id", "idempotency_key", unique=True),)

class ProcurementSettlementAllocation(Base):
    __tablename__ = "procurement_settlement_allocations"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    settlement_id: Mapped[int] = mapped_column(ForeignKey("procurement_settlements.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("accounting_invoices.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    accounting_payment_id: Mapped[int | None] = mapped_column(ForeignKey("accounting_invoice_payments.id"), nullable=True)
    __table_args__ = (Index("ix_procurement_settlement_allocation_invoice", "settlement_id", "invoice_id", unique=True),)

class ProcurementApprovalDelegation(Base):
    __tablename__ = "procurement_approval_delegations"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    principal_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    delegate_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(500))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_procurement_delegation_org_principal", "organization_id", "principal_user_id", "starts_at", "ends_at"),)

class ProcurementSupplierPortalToken(Base):
    __tablename__ = "procurement_supplier_portal_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("procurement_suppliers.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ProcurementInvoiceDiscrepancy(Base):
    __tablename__ = "procurement_invoice_discrepancies"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    supplier_invoice_id: Mapped[int] = mapped_column(ForeignKey("procurement_supplier_invoices.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="open")
    resolution_note: Mapped[str] = mapped_column(String(500), default="")
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ProcurementSupplierStatement(Base):
    __tablename__ = "procurement_supplier_statements"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("procurement_suppliers.id"), index=True)
    statement_reference: Mapped[str] = mapped_column(String(80))
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    closing_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reconciled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_procurement_supplier_statement_org_ref", "organization_id", "statement_reference", unique=True),)

class ProcurementSupplierStatementLine(Base):
    __tablename__ = "procurement_supplier_statement_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey("procurement_supplier_statements.id"), index=True)
    line_number: Mapped[int] = mapped_column()
    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    description: Mapped[str] = mapped_column(String(240))
    reference: Mapped[str] = mapped_column(String(120), default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    matched_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("accounting_invoices.id"), nullable=True)
    matched_payment_id: Mapped[int | None] = mapped_column(ForeignKey("accounting_invoice_payments.id"), nullable=True)
    matched_credit_note_id: Mapped[int | None] = mapped_column(ForeignKey("accounting_credit_notes.id"), nullable=True)
    matched_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_procurement_supplier_statement_line_no", "statement_id", "line_number", unique=True),)
