"""Tenant-scoped SACCO membership and KYC records."""
from datetime import datetime, timezone
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

def _now() -> datetime:
    return datetime.now(timezone.utc)

class SaccoMember(Base):
    """Member register. Government identity data is encrypted separately from searchable fields."""
    __tablename__ = "sacco_members"
    __table_args__ = (
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
