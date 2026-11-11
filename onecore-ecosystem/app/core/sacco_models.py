"""Tenant-scoped SACCO membership, KYC and financial ledger records."""
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Numeric,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SaccoMember(Base):
    """Member register. Government identity data is encrypted separately from searchable fields."""
    __tablename__ = "sacco_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_sacco_member_org_id"),
        UniqueConstraint("organization_id", "member_number", name="uq_sacco_member_org_number"),
        UniqueConstraint("organization_id", "identity_fingerprint", name="uq_sacco_member_org_identity"),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_sacco_member_org_idempotency"),
        CheckConstraint("status IN ('pending_kyc', 'active', 'rejected', 'suspended', 'exited')", name="ck_sacco_member_status"),
        Index("ix_sacco_member_org_status", "organization_id", "status"),
        Index("ix_sacco_member_org_branch_status", "organization_id", "branch_id", "status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True)
    member_number: Mapped[str] = mapped_column(String(40), nullable=False)
    full_name: Mapped[str] = mapped_column(String(180), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    identity_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_kyc", server_default="pending_kyc")
    review_note: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class SaccoFinancialTransaction(Base):
    """Mutable workflow envelope; posted value is represented only by an immutable ledger entry."""
    __tablename__ = "sacco_financial_transactions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_sacco_financial_org_id"),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_sacco_financial_org_idempotency"),
        ForeignKeyConstraint(
            ["organization_id", "member_id"], ["sacco_members.organization_id", "sacco_members.id"],
            ondelete="RESTRICT", name="fk_sacco_financial_member_tenant",
        ),
        CheckConstraint("account_type IN ('savings', 'shares')", name="ck_sacco_financial_account_type"),
        CheckConstraint("transaction_type IN ('deposit', 'withdrawal', 'share_contribution')", name="ck_sacco_financial_transaction_type"),
        CheckConstraint("status IN ('pending_approval', 'posted', 'rejected')", name="ck_sacco_financial_status"),
        CheckConstraint("amount > 0", name="ck_sacco_financial_amount_positive"),
        CheckConstraint(
            "(account_type = 'savings' AND transaction_type IN ('deposit', 'withdrawal')) "
            "OR (account_type = 'shares' AND transaction_type = 'share_contribution')",
            name="ck_sacco_financial_type_account_match",
        ),
        Index("ix_sacco_financial_org_member_created", "organization_id", "member_id", "created_at"),
        Index("ix_sacco_financial_org_status", "organization_id", "status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    member_id: Mapped[int] = mapped_column(nullable=False, index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True)
    account_type: Mapped[str] = mapped_column(String(16), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(24), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reference: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="posted", server_default="posted")
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class SaccoLedgerEntry(Base):
    """Append-only member savings/share subledger; corrections require a compensating entry."""
    __tablename__ = "sacco_ledger_entries"
    __table_args__ = (
        UniqueConstraint("transaction_id", name="uq_sacco_ledger_transaction"),
        ForeignKeyConstraint(
            ["organization_id", "member_id"], ["sacco_members.organization_id", "sacco_members.id"],
            ondelete="RESTRICT", name="fk_sacco_ledger_member_tenant",
        ),
        ForeignKeyConstraint(
            ["organization_id", "transaction_id"],
            ["sacco_financial_transactions.organization_id", "sacco_financial_transactions.id"],
            ondelete="RESTRICT", name="fk_sacco_ledger_transaction_tenant",
        ),
        CheckConstraint("account_type IN ('savings', 'shares')", name="ck_sacco_ledger_account_type"),
        CheckConstraint("signed_amount <> 0", name="ck_sacco_ledger_nonzero_amount"),
        Index("ix_sacco_ledger_org_member_account", "organization_id", "member_id", "account_type", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    member_id: Mapped[int] = mapped_column(nullable=False, index=True)
    transaction_id: Mapped[int] = mapped_column(nullable=False)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True)
    account_type: Mapped[str] = mapped_column(String(16), nullable=False)
    signed_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reference: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
