from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import User, Membership, Organization
from app.core.security import current_user, set_verified_organization_context
from app.core.host_routing import organization_for_host
from app.core.authorization import has_module_permission
from app.core.platform_commerce_models import OrganizationSubscription, SubscriptionPlan
from datetime import datetime, timezone


def _module_for_path(path: str) -> str | None:
    """Map API namespaces to the single entitlement key used by the workspace."""
    normalized = (path or "").lower()
    if normalized.startswith("/api/v1/records/"):
        parts = normalized.split("/")
        return parts[4] if len(parts) > 4 else None
    prefixes = (
        ("/api/v1/accounting", "accounting"),
        ("/api/v1/finance", "accounting"),
        ("/api/v1/pos", "pos"),
        ("/api/v1/inventory", "inventory"),
        ("/api/v1/procurement", "procurement"),
        ("/api/v1/crm", "crm"),
        ("/api/v1/school", "school"),
        ("/api/v1/healthcare", "hospital"),
        ("/api/v1/pharmacy-lab", "pharmacy"),
        ("/api/v1/hr", "hr"),
        ("/api/v1/payroll", "payroll"),
        ("/api/v1/sacco", "sacco"),
        ("/api/v1/property", "property"),
        ("/api/v1/hotel", "hotel"),
        ("/api/v1/restaurant", "restaurant"),
        ("/api/v1/reports", "reports"),
        ("/api/v1/analytics", "reports"),
        ("/api/v1/documents", "documents"),
    )
    for prefix, module_key in prefixes:
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return module_key
    return None


def _module_entitlements(value) -> set[str]:
    if not isinstance(value, dict):
        return set()
    raw = value.get("modules", value.get("module_access", []))
    if isinstance(raw, dict):
        return {str(key).lower() for key, enabled in raw.items() if enabled is True}
    if isinstance(raw, list):
        return {str(key).lower() for key in raw if isinstance(key, str)}
    return set()


def _enforce_module_entitlement(db: Session, membership: Membership, module_key: str) -> None:
    if not has_module_permission(membership, module_key, "read"):
        raise HTTPException(403, "Your organization role does not grant access to this module")
    now = datetime.now(timezone.utc)
    subscriptions = db.query(OrganizationSubscription).filter_by(
        organization_id=membership.organization_id
    ).order_by(OrganizationSubscription.created_at.desc()).limit(20).all()
    # Existing tenants without a subscription record retain their current access
    # during migration. Once a subscription lifecycle exists, only an in-term
    # active/trialing subscription can grant business-module access.
    if not subscriptions:
        return
    active = None
    for row in subscriptions:
        if row.status not in {"active", "trialing"}:
            continue
        start, end = row.starts_at, row.ends_at
        if start and start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if start and start > now:
            continue
        if end and end <= now:
            continue
        active = row
        break
    if active is None:
        raise HTTPException(403, "This organization has no active subscription for business modules")
    override = active.entitlements_override
    plan = db.get(SubscriptionPlan, active.plan_id)
    entitlements = override if override is not None else ((plan.entitlements or {}) if plan else {})
    allowed = _module_entitlements(entitlements)
    if "*" not in allowed and module_key not in allowed:
        raise HTTPException(403, "This organization subscription does not include the requested module")


def active_membership(
    request: Request,
    x_organization_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    host_org = organization_for_host(db, request.url.hostname or "")
    if host_org is not None:
        if x_organization_id is not None and x_organization_id != host_org.id:
            raise HTTPException(404, "Organization not found for this host")
        organization_id = host_org.id
    else:
        organization_id = x_organization_id
    if organization_id is None:
        raise HTTPException(400, "X-Organization-ID is required on the shared OneCore host")
    membership = db.query(Membership).filter_by(
        user_id=user.id, organization_id=organization_id, is_active=True
    ).first()
    org = db.get(Organization, organization_id)
    if not membership or not org or not org.is_active:
        raise HTTPException(403, "No active access to this organization")

    # The tenant GUC is deliberately set only after the server has verified an
    # active membership. PostgreSQL RLS policies use this transaction-local
    # context for tenant-scoped reads/writes made by downstream route handlers.
    set_verified_organization_context(db, organization_id)
    module_key = _module_for_path(request.url.path)
    if module_key:
        _enforce_module_entitlement(db, membership, module_key)
    return membership
