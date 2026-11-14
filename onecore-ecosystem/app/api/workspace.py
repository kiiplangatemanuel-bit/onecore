"""Unified authenticated workspace context and role-filtered navigation."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.authorization import branch_scope_ids, has_module_permission
from app.core.database import get_db
from app.core.models import AuditEvent, Branch, Membership, Organization, Record, User
from app.core.platform_commerce_models import OrganizationSubscription, SubscriptionPlan
from app.core.security import current_user
from app.core.tenancy import active_membership

router = APIRouter(prefix="/api/v1/workspace", tags=["unified workspace"])

# One application, one route namespace. These are capabilities inside the
# workspace, not separately deployed applications.
MODULES = [
    {"key": "dashboard", "label": "Dashboard", "path": "/app", "group": "Workspace"},
    {"key": "accounting", "label": "Accounting", "path": "/app/accounting", "group": "Business"},
    {"key": "crm", "label": "CRM", "path": "/app/crm", "group": "Business"},
    {"key": "inventory", "label": "Inventory", "path": "/app/inventory", "group": "Business"},
    {"key": "procurement", "label": "Procurement", "path": "/app/procurement", "group": "Business"},
    {"key": "pos", "label": "Point of Sale", "path": "/app/pos", "group": "Business"},
    {"key": "hr", "label": "Human Resources", "path": "/app/hr", "group": "Business"},
    {"key": "payroll", "label": "Payroll", "path": "/app/payroll", "group": "Business"},
    {"key": "school", "label": "School", "path": "/app/school", "group": "Industry"},
    {"key": "hospital", "label": "Hospital", "path": "/app/hospital", "group": "Industry"},
    {"key": "pharmacy", "label": "Pharmacy", "path": "/app/pharmacy", "group": "Industry"},
    {"key": "laboratory", "label": "Laboratory", "path": "/app/laboratory", "group": "Industry"},
    {"key": "sacco", "label": "SACCO & Microfinance", "path": "/app/sacco", "group": "Industry"},
    {"key": "property", "label": "Property", "path": "/app/property", "group": "Industry"},
    {"key": "hotel", "label": "Hotel", "path": "/app/hotel", "group": "Industry"},
    {"key": "restaurant", "label": "Restaurant", "path": "/app/restaurant", "group": "Industry"},
    {"key": "reports", "label": "Reports", "path": "/app/reports", "group": "Shared Services"},
    {"key": "documents", "label": "Documents", "path": "/app/documents", "group": "Shared Services"},
]


def _entitled_modules(entitlements):
    """Accept the documented list or map representation; never infer grants."""
    entitlements = entitlements if isinstance(entitlements, dict) else {}
    raw = entitlements.get("modules", entitlements.get("module_access", []))
    if isinstance(raw, dict):
        return {str(key).lower() for key, enabled in raw.items() if enabled is True}
    if isinstance(raw, list):
        return {str(key).lower() for key in raw if isinstance(key, str)}
    return set()


def _current_plan(db: Session, organization_id: int):
    now = datetime.now(timezone.utc)
    rows = db.query(OrganizationSubscription).filter(
        OrganizationSubscription.organization_id == organization_id,
        OrganizationSubscription.status.in_(("active", "trialing")),
    ).order_by(OrganizationSubscription.created_at.desc()).limit(10).all()
    for row in rows:
        start = row.starts_at
        end = row.ends_at
        if start and start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if start and start > now:
            continue
        if end and end <= now:
            continue
        return row, db.get(SubscriptionPlan, row.plan_id)
    return None, None


@router.get("/context")
def workspace_context(
    membership=Depends(active_membership),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    organization = db.get(Organization, membership.organization_id)
    subscription, plan = _current_plan(db, membership.organization_id)
    entitlements = (subscription.entitlements_override if subscription and subscription.entitlements_override is not None else ((plan.entitlements or {}) if plan else {}))
    entitled = _entitled_modules(entitlements)
    has_subscription_history = db.query(OrganizationSubscription.id).filter_by(
        organization_id=membership.organization_id
    ).first() is not None
    legacy_access = not subscription and not has_subscription_history
    modules = []
    for item in MODULES:
        key = item["key"]
        if key == "dashboard" or (legacy_access or (subscription and ("*" in entitled or key in entitled))):
            if key == "dashboard" or has_module_permission(membership, key, "read"):
                modules.append(item)

    allowed_branches = branch_scope_ids(membership)
    branch_query = db.query(Branch).filter_by(
        organization_id=membership.organization_id, is_active=True
    )
    if allowed_branches is not None:
        branch_query = branch_query.filter(Branch.id.in_(allowed_branches))
    branches = branch_query.order_by(Branch.name.asc()).all()

    organizations = db.query(Organization).join(
        Membership, Membership.organization_id == Organization.id
    ).filter(
        Membership.user_id == user.id, Membership.is_active.is_(True),
        Organization.is_active.is_(True),
    ).order_by(Organization.name.asc()).all()

    return {
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name,
                 "platform_role": user.platform_role},
        "organization": {"id": organization.id, "name": organization.name,
                         "slug": organization.slug, "industry": organization.industry,
                         "currency": organization.currency, "timezone": organization.timezone},
        "organizations": [{"id": x.id, "name": x.name, "slug": x.slug} for x in organizations],
        "membership": {"role": membership.role, "branch_scope": membership.branch_scope},
        "branches": [{"id": x.id, "code": x.code, "name": x.name} for x in branches],
        "subscription": ({"id": subscription.id, "status": subscription.status,
                         "plan": plan.code if plan else None,
                         "ends_at": subscription.ends_at.isoformat() if subscription.ends_at else None}
                        if subscription else None),
        "entitlements": ({"modules": ["*"], "legacy_access": True} if legacy_access else entitlements),
        "modules": modules,
    }


@router.get("/dashboard")
def workspace_dashboard(
    membership=Depends(active_membership),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Tenant-scoped baseline KPIs; specialist widgets are added by their modules."""
    org_id = membership.organization_id
    active_members = db.query(func.count(Membership.id)).filter_by(
        organization_id=org_id, is_active=True
    ).scalar() or 0
    active_branches = db.query(func.count(Branch.id)).filter_by(
        organization_id=org_id, is_active=True
    ).scalar() or 0
    records = db.query(func.count(Record.id)).filter_by(
        organization_id=org_id
    ).scalar() or 0
    recent = db.query(AuditEvent).filter_by(
        organization_id=org_id
    ).order_by(AuditEvent.created_at.desc()).limit(8).all()
    return {
        "organization_id": org_id,
        "kpis": {"active_members": active_members, "active_branches": active_branches,
                 "business_records": records},
        "recent_activity": [{"id": x.id, "action": x.action, "resource_type": x.resource_type,
                             "created_at": x.created_at.isoformat()} for x in recent],
        "role": membership.role,
    }
