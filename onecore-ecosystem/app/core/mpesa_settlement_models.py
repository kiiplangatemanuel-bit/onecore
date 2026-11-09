"""Durable tenant-scoped M-Pesa settlement statement imports."""
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def now():
    return datetime.now(timezone.utc)


class MpesaSettlementBatch(Base):
    __tablename__ = "mpesa_settlement_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(24), default="daraja_statement")
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    status: Mapped[str] = mapped_column(String(24), default="imported")
    total_lines: Mapped[int] = mapped_column(default=0)
    matched_lines: Mapped[int] = mapped_column(default=0)
    exception_lines: Mapped[int] = mapped_column(default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    matched_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    imported_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("organization_id", "idempotency_key", name="uq_mpesa_settlement_org_key"),)


class MpesaSettlementLine(Base):
    __tablename__ = "mpesa_settlement_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("mpesa_settlement_batches.id", ondelete="CASCADE"), index=True)
    receipt_number: Mapped[str] = mapped_column(String(40))
    transaction_type: Mapped[str] = mapped_column(String(12))
    transaction_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    account_reference: Mapped[str] = mapped_column(String(120), default="")
    matched_type: Mapped[str] = mapped_column(String(16), default="")
    matched_id: Mapped[int | None] = mapped_column(nullable=True)
    expected_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="unmatched")
    exception_detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("ix_mpesa_settlement_org_receipt", "organization_id", "receipt_number"),
        Index("ix_mpesa_settlement_batch_status", "batch_id", "status"),
    )
