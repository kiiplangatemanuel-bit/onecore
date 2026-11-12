"""Platform-wide security metadata shared by all API workers."""
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PlatformRateLimitBucket(Base):
    """One HMAC-keyed fixed-window counter; it never stores a client IP or email."""

    __tablename__ = "platform_rate_limit_buckets"
    __table_args__ = (
        CheckConstraint("request_count > 0", name="ck_platform_rate_limit_count_positive"),
        Index("ix_platform_rate_limit_buckets_expires_at", "expires_at"),
    )

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=func.now()
    )
