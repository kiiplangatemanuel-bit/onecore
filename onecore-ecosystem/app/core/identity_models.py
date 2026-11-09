"""Account-owned identity records that are not scoped to a business tenant."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UserSession(Base):
    """One revocable OneCore bearer-token session for one account and device."""

    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False)
    auth_method: Mapped[str] = mapped_column(String(24), nullable=False, default="password")
    mfa_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    device_name: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    user_agent: Mapped[str] = mapped_column(String(512), nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")

    __table_args__ = (
        Index("ix_user_sessions_user_created", "user_id", "created_at"),
        Index("ix_user_sessions_user_active", "user_id", "revoked_at", "expires_at"),
    )


class PortalAuthorizationAssurance(Base):
    """MFA assurance inherited by a one-time PKCE portal authorization code."""

    __tablename__ = "portal_authorization_assurance"

    portal_code_id: Mapped[int] = mapped_column(
        ForeignKey("portal_authorization_codes.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mfa_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
