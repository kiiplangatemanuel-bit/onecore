"""Tenant-scoped foreign-currency and statutory-remittance records."""
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Index, JSON, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def now():
    return datetime.now(timezone.utc)


class AccountingFxRate(Base):
    __tablename__ = "accounting_fx_rates"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    rate_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    units_per_base: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    source: Mapped[str] = mapped_column(String(80))
    reference: Mapped[str] = mapped_column(String(120), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("uq_accounting_fx_rate_org_currency_date_source", "organization_id", "currency", "rate_date", "source", unique=True),)


class AccountingFxPosting(Base):
    __tablename__ = "accounting_fx_postings"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("accounting_journals.id"), unique=True)
    rate_id: Mapped[int] = mapped_column(ForeignKey("accounting_fx_rates.id"))
    currency: Mapped[str] = mapped_column(String(3))
    foreign_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    base_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64))
    reference: Mapped[str] = mapped_column(String(120), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("uq_accounting_fx_posting_org_key", "organization_id", "idempotency_key", unique=True),)


class AccountingFxRevaluation(Base):
    __tablename__ = "accounting_fx_revaluations"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("accounting_journals.id"), unique=True)
    currency: Mapped[str] = mapped_column(String(3))
    valuation_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closing_rate: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    total_gain: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    total_loss: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    position_snapshot: Mapped[list] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("uq_accounting_fx_revaluation_org_key", "organization_id", "idempotency_key", unique=True),)


class PayrollStatutoryBatch(Base):
    __tablename__ = "payroll_statutory_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    status: Mapped[str] = mapped_column(String(24), default="draft")
    totals: Mapped[dict] = mapped_column(JSON)
    employee_lines: Mapped[list] = mapped_column(JSON, default=list)
    source_run_ids: Mapped[list] = mapped_column(JSON)
    payment_journal_id: Mapped[int | None] = mapped_column(ForeignKey("accounting_journals.id"), nullable=True, unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    paid_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    payment_reference: Mapped[str] = mapped_column(String(120), default="")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("uq_payroll_statutory_batch_org_key", "organization_id", "idempotency_key", unique=True),
        Index("uq_payroll_statutory_batch_org_payment_reference", "organization_id", "payment_reference", unique=True,
              sqlite_where=text("payment_reference <> ''"), postgresql_where=text("payment_reference <> ''")),
    )
