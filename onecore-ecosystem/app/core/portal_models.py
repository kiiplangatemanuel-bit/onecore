from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, JSON, Text, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

def _now():
    return datetime.now(timezone.utc)

class PortalResource(Base):
    """A portal-scoped resource with explicit public, owner and tenant visibility."""
    __tablename__ = "portal_resources"
    id: Mapped[int] = mapped_column(primary_key=True)
    portal: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="private")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)
    __table_args__ = (
        Index("ix_portal_resources_public", "portal", "visibility", "status"),
        Index("ix_portal_resources_tenant", "portal", "organization_id", "resource_type"),
        Index("ix_portal_resources_owner", "portal", "owner_user_id", "resource_type"),
    )
