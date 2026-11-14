"""Restricted OneCore platform administration APIs."""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import os
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import AuditEvent, Membership, Organization, User, DeveloperApiKey, DeveloperApiKeyUsage, PortalWorkflowRecord
from app.core.platform_commerce_models import OrganizationSubscription, SubscriptionPayment, SubscriptionPlan
from app.core.security import require_platform_admin

router = APIRouter(prefix="/api/v1/admin/platform", tags=["platform administration"])


def _audit(db, actor, org_id, action, kind, resource_id, detail=""):
    db.add(AuditEvent(actor_user_id=actor.id, organization_id=org_id, action=action,
                      resource_type=kind, resource_id=str(resource_id), detail=detail))


def _org(row, members=0):
    return {"id": row.id, "name": row.name, "slug": row.slug, "industry": row.industry,
            "country": row.country, "currency": row.currency, "is_active": row.is_active,
            "created_at": row.created_at.isoformat(), "member_count": members}


def _user(row, membership_count=0):
    return {"id": row.id, "email": row.email, "full_name": row.full_name,
            "platform_role": row.platform_role, "is_active": row.is_active,
            "created_at": row.created_at.isoformat(), "organization_count": membership_count}


@router.get("/overview")
def platform_overview(user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return {
        "users": db.query(func.count(User.id)).scalar() or 0,
        "active_users": db.query(func.count(User.id)).filter_by(is_active=True).scalar() or 0,
        "organizations": db.query(func.count(Organization.id)).scalar() or 0,
        "active_organizations": db.query(func.count(Organization.id)).filter_by(is_active=True).scalar() or 0,
        "memberships": db.query(func.count(Membership.id)).filter_by(is_active=True).scalar() or 0,
        "pending_subscription_payments": db.query(func.count(SubscriptionPayment.id)).filter_by(status="pending_verification").scalar() or 0,
        "active_subscriptions": db.query(func.count(OrganizationSubscription.id)).filter_by(status="active").scalar() or 0,
        "recent_audit_events": db.query(func.count(AuditEvent.id)).filter(
            AuditEvent.created_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        ).scalar() or 0,
    }


@router.get("/organizations")
def list_platform_organizations(q: str = Query(default="", max_length=120),
                                active: bool | None = None, limit: int = Query(default=100, ge=1, le=500),
                                user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    query = db.query(Organization)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(or_(Organization.name.ilike(term), Organization.slug.ilike(term)))
    if active is not None:
        query = query.filter_by(is_active=active)
    rows = query.order_by(Organization.created_at.desc()).limit(limit).all()
    counts = dict(db.query(Membership.organization_id, func.count(Membership.id)).filter(
        Membership.is_active.is_(True), Membership.organization_id.in_([x.id for x in rows])
    ).group_by(Membership.organization_id).all()) if rows else {}
    return [_org(x, counts.get(x.id, 0)) for x in rows]


class OrganizationStatusIn(BaseModel):
    is_active: bool
    reason: str = Field(min_length=3, max_length=500)


@router.patch("/organizations/{organization_id}/status")
def set_organization_status(organization_id: int, payload: OrganizationStatusIn,
                             user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    row = db.query(Organization).filter_by(id=organization_id).with_for_update().first()
    if not row:
        raise HTTPException(404, "Organization not found")
    if row.is_active == payload.is_active:
        return _org(row)
    row.is_active = payload.is_active
    _audit(db, user, row.id, "platform.organization_status_changed", "organization", row.id,
           f"is_active={payload.is_active};reason={payload.reason.strip()}")
    db.commit(); db.refresh(row)
    return _org(row)


@router.get("/users")
def list_platform_users(q: str = Query(default="", max_length=120),
                        active: bool | None = None, limit: int = Query(default=100, ge=1, le=500),
                        user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    query = db.query(User)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(or_(User.email.ilike(term), User.full_name.ilike(term)))
    if active is not None:
        query = query.filter_by(is_active=active)
    rows = query.order_by(User.created_at.desc()).limit(limit).all()
    counts = dict(db.query(Membership.user_id, func.count(Membership.id)).filter(
        Membership.is_active.is_(True), Membership.user_id.in_([x.id for x in rows])
    ).group_by(Membership.user_id).all()) if rows else {}
    return [_user(x, counts.get(x.id, 0)) for x in rows]


class UserStatusIn(BaseModel):
    is_active: bool
    reason: str = Field(min_length=3, max_length=500)


@router.patch("/users/{user_id}/status")
def set_user_status(user_id: int, payload: UserStatusIn,
                    user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    row = db.query(User).filter_by(id=user_id).with_for_update().first()
    if not row:
        raise HTTPException(404, "User not found")
    if row.id == user.id and not payload.is_active:
        raise HTTPException(409, "You cannot deactivate your own active administrator account")
    if row.platform_role == "root_superadmin":
        raise HTTPException(403, "Root Superadmin accounts cannot be suspended through this endpoint")
    if row.platform_role == "platform_admin" and user.platform_role != "root_superadmin":
        raise HTTPException(403, "Only a Root Superadmin can suspend another platform administrator")
    if row.is_active != payload.is_active:
        row.is_active = payload.is_active
        row.auth_version = (row.auth_version or 0) + 1
        _audit(db, user, None, "platform.user_status_changed", "user", row.id,
               f"is_active={payload.is_active};reason={payload.reason.strip()}")
        db.commit(); db.refresh(row)
    return _user(row)


@router.get("/audit")
def platform_audit(q: str = Query(default="", max_length=120),
                   limit: int = Query(default=200, ge=1, le=500),
                   user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    query = db.query(AuditEvent)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(or_(AuditEvent.action.ilike(term), AuditEvent.resource_type.ilike(term),
                                 AuditEvent.resource_id.ilike(term), AuditEvent.detail.ilike(term)))
    rows = query.order_by(AuditEvent.created_at.desc()).limit(limit).all()
    return [{"id": x.id, "organization_id": x.organization_id, "actor_user_id": x.actor_user_id,
             "action": x.action, "resource_type": x.resource_type, "resource_id": x.resource_id,
             "detail": x.detail, "created_at": x.created_at.isoformat()} for x in rows]


@router.get("/subscriptions")
def list_platform_subscriptions(status: str = Query(default="all"),
                                user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    query = db.query(OrganizationSubscription)
    if status != "all":
        query = query.filter_by(status=status)
    rows = query.order_by(OrganizationSubscription.created_at.desc()).limit(500).all()
    plans = {x.id: x for x in db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id.in_([r.plan_id for r in rows])).all()} if rows else {}
    orgs = {x.id: x for x in db.query(Organization).filter(
        Organization.id.in_([r.organization_id for r in rows])).all()} if rows else {}
    return [{"id": x.id, "organization_id": x.organization_id,
             "organization": orgs[x.organization_id].name if x.organization_id in orgs else "Unknown",
             "plan": plans[x.plan_id].name if x.plan_id in plans else "Unknown",
             "status": x.status, "starts_at": x.starts_at.isoformat() if x.starts_at else None,
             "ends_at": x.ends_at.isoformat() if x.ends_at else None,
             "created_at": x.created_at.isoformat()} for x in rows]


class PlanIn(BaseModel):
    code: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=4000)
    amount: Decimal = Field(ge=0, le=100000000)
    currency: str = Field(default="KES", pattern=r"^[A-Z]{3}$")
    interval: Literal["monthly", "yearly"] = "monthly"
    entitlements: dict = Field(default_factory=dict)
    is_active: bool = True


def _plan(row):
    return {"id": row.id, "code": row.code, "name": row.name, "description": row.description,
            "amount": str(row.amount), "currency": row.currency, "interval": row.interval,
            "entitlements": row.entitlements or {}, "is_active": row.is_active}


@router.get("/subscription-plans")
def admin_list_plans(user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return [_plan(x) for x in db.query(SubscriptionPlan).order_by(SubscriptionPlan.created_at.desc()).all()]


@router.post("/subscription-plans", status_code=201)
def create_plan(payload: PlanIn, user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    if db.query(SubscriptionPlan).filter_by(code=payload.code).first():
        raise HTTPException(409, "A plan with this code already exists")
    row = SubscriptionPlan(**payload.model_dump())
    db.add(row)
    _audit(db, user, None, "platform.subscription_plan_created", "subscription_plan", payload.code)
    db.commit(); db.refresh(row)
    return _plan(row)


@router.patch("/subscription-plans/{plan_id}")
def update_plan(plan_id: int, payload: PlanIn, user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    row = db.query(SubscriptionPlan).filter_by(id=plan_id).with_for_update().first()
    if not row:
        raise HTTPException(404, "Subscription plan not found")
    if row.code != payload.code and db.query(SubscriptionPlan).filter_by(code=payload.code).first():
        raise HTTPException(409, "A plan with this code already exists")
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    _audit(db, user, None, "platform.subscription_plan_updated", "subscription_plan", row.id, row.code)
    db.commit(); db.refresh(row)
    return _plan(row)


class OrganizationCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    owner_user_id: int
    industry: str = Field(default="general", min_length=2, max_length=100)
    country: str = Field(default="KE", pattern=r"^[A-Z]{2}$")
    currency: str = Field(default="KES", pattern=r"^[A-Z]{3}$")
    timezone: str = Field(default="Africa/Nairobi", min_length=1, max_length=80)


@router.post("/organizations", status_code=201)
def create_platform_organization(payload: OrganizationCreateIn,
                                 user: User = Depends(require_platform_admin),
                                 db: Session = Depends(get_db)):
    owner = db.query(User).filter_by(id=payload.owner_user_id, is_active=True).first()
    if not owner:
        raise HTTPException(404, "Active owner user not found")
    if db.query(Organization).filter_by(slug=payload.slug).first():
        raise HTTPException(409, "Organization slug already exists")
    row = Organization(name=payload.name.strip(), slug=payload.slug,
                       owner_user_id=owner.id, industry=payload.industry.strip().lower(),
                       country=payload.country, currency=payload.currency,
                       timezone=payload.timezone, is_active=True)
    db.add(row)
    db.flush()
    membership = Membership(user_id=owner.id, organization_id=row.id,
                            role="org_admin", branch_scope="*", is_active=True)
    db.add(membership)
    _audit(db, user, row.id, "platform.organization_created", "organization", row.id,
           f"owner_user_id={owner.id};industry={row.industry}")
    db.commit()
    db.refresh(row)
    return _org(row, 1)


class MembershipAdminIn(BaseModel):
    role: str = Field(min_length=2, max_length=50)
    branch_scope: str = Field(default="*", max_length=500)
    is_active: bool = True


@router.get("/organizations/{organization_id}/memberships")
def list_organization_memberships(organization_id: int,
                                  user: User = Depends(require_platform_admin),
                                  db: Session = Depends(get_db)):
    if not db.get(Organization, organization_id):
        raise HTTPException(404, "Organization not found")
    rows = db.query(Membership).filter_by(organization_id=organization_id).order_by(Membership.id).all()
    users = {x.id: x for x in db.query(User).filter(
        User.id.in_([m.user_id for m in rows])).all()} if rows else {}
    return [{"id": m.id, "user_id": m.user_id,
             "email": users[m.user_id].email if m.user_id in users else None,
             "full_name": users[m.user_id].full_name if m.user_id in users else None,
             "role": m.role, "branch_scope": m.branch_scope, "is_active": m.is_active}
            for m in rows]


@router.patch("/memberships/{membership_id}")
def update_platform_membership(membership_id: int, payload: MembershipAdminIn,
                               user: User = Depends(require_platform_admin),
                               db: Session = Depends(get_db)):
    from app.core.models import Branch
    from app.core.authorization import ROLE_PERMISSIONS
    row = db.query(Membership).filter_by(id=membership_id).with_for_update().first()
    if not row:
        raise HTTPException(404, "Membership not found")
    if payload.role not in ROLE_PERMISSIONS:
        raise HTTPException(422, "Unsupported organization role")
    scope = payload.branch_scope.strip()
    if scope != "*":
        ids = [x.strip() for x in scope.split(",")]
        if not ids or len(ids) != len(set(ids)) or any(not x for x in ids):
            raise HTTPException(422, "Branch scope must contain unique branch IDs")
        found = {x[0] for x in db.query(Branch.id).filter(
            Branch.organization_id == row.organization_id,
            Branch.is_active.is_(True), Branch.id.in_(ids)).all()}
        if found != set(ids):
            raise HTTPException(422, "Branch scope must reference active branches in this organization")
        scope = ",".join(ids)
    row.role = payload.role
    row.branch_scope = scope
    row.is_active = payload.is_active
    _audit(db, user, row.organization_id, "platform.membership_updated",
           "membership", row.id,
           f"role={row.role};branch_scope={row.branch_scope};is_active={row.is_active}")
    db.commit()
    return {"id": row.id, "user_id": row.user_id, "organization_id": row.organization_id,
            "role": row.role, "branch_scope": row.branch_scope, "is_active": row.is_active}


class OrganizationSubscriptionGrantIn(BaseModel):
    plan_id: int
    status: Literal["active", "trialing", "suspended"] = "active"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    entitlements_override: dict | None = None


@router.put("/organizations/{organization_id}/subscription")
def grant_organization_subscription(organization_id: int, payload: OrganizationSubscriptionGrantIn,
                                    user: User = Depends(require_platform_admin),
                                    db: Session = Depends(get_db)):
    org = db.query(Organization).filter_by(id=organization_id).with_for_update().first()
    if not org:
        raise HTTPException(404, "Organization not found")
    plan = db.query(SubscriptionPlan).filter_by(id=payload.plan_id, is_active=True).first()
    if not plan:
        raise HTTPException(404, "Active subscription plan not found")
    starts = payload.starts_at or datetime.now(timezone.utc)
    ends = payload.ends_at
    if starts.tzinfo is None:
        starts = starts.replace(tzinfo=timezone.utc)
    if ends is not None and ends.tzinfo is None:
        ends = ends.replace(tzinfo=timezone.utc)
    if ends is not None and ends <= starts:
        raise HTTPException(422, "Subscription end must be after its start")
    previous = db.query(OrganizationSubscription).filter(
        OrganizationSubscription.organization_id == organization_id,
        OrganizationSubscription.status.in_(("active", "trialing", "pending_payment", "past_due")),
    ).with_for_update().all()
    for old in previous:
        old.status = "superseded"
        old.auto_renew = False
    row = OrganizationSubscription(
        organization_id=organization_id, plan_id=plan.id, status=payload.status,
        amount=plan.amount, currency=plan.currency, billing_interval=plan.interval,
        starts_at=starts, ends_at=ends, auto_renew=False, created_by=user.id,
        entitlements_override=payload.entitlements_override,
    )
    db.add(row)
    _audit(db, user, organization_id, "platform.organization_entitlements_granted",
           "organization_subscription", organization_id,
           f"plan={plan.code};status={payload.status};modules={sorted((plan.entitlements or {}).get('modules', []))}")
    db.commit()
    db.refresh(row)
    effective = row.entitlements_override if row.entitlements_override is not None else (plan.entitlements or {})
    return {"id": row.id, "organization_id": organization_id, "plan": _plan(plan),
            "status": row.status, "starts_at": row.starts_at.isoformat(),
            "ends_at": row.ends_at.isoformat() if row.ends_at else None,
            "entitlements_override": row.entitlements_override,
            "effective_entitlements": effective}


class OrganizationEntitlementsIn(BaseModel):
    entitlements: dict = Field(default_factory=dict)


@router.get("/organizations/{organization_id}/entitlements")
def get_organization_entitlements(organization_id: int,
                                  user: User = Depends(require_platform_admin),
                                  db: Session = Depends(get_db)):
    org = db.get(Organization, organization_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    subscription, plan = _current_organization_subscription(db, organization_id)
    if not subscription:
        return {"organization_id": organization_id, "subscription": None,
                "entitlements_override": None, "effective_entitlements": {}}
    effective = subscription.entitlements_override if subscription.entitlements_override is not None else ((plan.entitlements or {}) if plan else {})
    return {"organization_id": organization_id,
            "subscription": {"id": subscription.id, "status": subscription.status,
                             "plan_id": subscription.plan_id, "plan_code": plan.code if plan else None},
            "entitlements_override": subscription.entitlements_override,
            "effective_entitlements": effective}


def _current_organization_subscription(db: Session, organization_id: int):
    now = datetime.now(timezone.utc)
    rows = db.query(OrganizationSubscription).filter(
        OrganizationSubscription.organization_id == organization_id,
        OrganizationSubscription.status.in_(("active", "trialing")),
    ).order_by(OrganizationSubscription.created_at.desc()).limit(10).all()
    for row in rows:
        start, end = row.starts_at, row.ends_at
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


@router.patch("/organizations/{organization_id}/entitlements")
def update_organization_entitlements(organization_id: int, payload: OrganizationEntitlementsIn,
                                     user: User = Depends(require_platform_admin),
                                     db: Session = Depends(get_db)):
    subscription, plan = _current_organization_subscription(db, organization_id)
    if not subscription or not plan:
        raise HTTPException(409, "Assign an active subscription before changing organization entitlements")
    modules = payload.entitlements.get("modules", payload.entitlements.get("module_access", []))
    if isinstance(modules, list):
        if any(not isinstance(item, str) or not item.strip() for item in modules):
            raise HTTPException(422, "Module entitlements must be non-empty module keys")
        payload.entitlements["modules"] = sorted(set(item.strip().lower() for item in modules))
    elif isinstance(modules, dict):
        payload.entitlements["modules"] = {str(key).strip().lower(): value is True for key, value in modules.items()}
    else:
        raise HTTPException(422, "Entitlements must include modules as a list or boolean map")
    subscription.entitlements_override = payload.entitlements
    _audit(db, user, organization_id, "platform.organization_entitlements_updated",
           "organization_subscription", subscription.id,
           f"modules={payload.entitlements['modules']}")
    db.commit()
    return {"organization_id": organization_id, "subscription_id": subscription.id,
            "entitlements_override": subscription.entitlements_override,
            "effective_entitlements": subscription.entitlements_override}


class SubscriptionLifecycleIn(BaseModel):
    status: Literal["active", "trialing", "suspended", "cancelled", "past_due"]
    reason: str = Field(min_length=3, max_length=500)
    ends_at: datetime | None = None


@router.patch("/subscriptions/{subscription_id}/lifecycle")
def update_subscription_lifecycle(subscription_id: int, payload: SubscriptionLifecycleIn,
                                   user: User = Depends(require_platform_admin),
                                   db: Session = Depends(get_db)):
    row = db.query(OrganizationSubscription).filter_by(id=subscription_id).with_for_update().first()
    if not row:
        raise HTTPException(404, "Subscription not found")
    if payload.ends_at is not None:
        ends = payload.ends_at
        if ends.tzinfo is None:
            ends = ends.replace(tzinfo=timezone.utc)
        if row.starts_at and ends <= row.starts_at:
            raise HTTPException(422, "Subscription end must be after its start")
        row.ends_at = ends
    row.status = payload.status
    if payload.status in {"suspended", "cancelled", "past_due"}:
        row.auto_renew = False
    _audit(db, user, row.organization_id, "platform.subscription_lifecycle_changed",
           "organization_subscription", row.id,
           f"status={payload.status};reason={payload.reason.strip()}")
    db.commit()
    return {"id": row.id, "organization_id": row.organization_id,
            "status": row.status, "starts_at": row.starts_at.isoformat() if row.starts_at else None,
            "ends_at": row.ends_at.isoformat() if row.ends_at else None}


class DeveloperCredentialCreateIn(BaseModel):
    organization_id: int = Field(gt=0)
    name: str = Field(min_length=2, max_length=120)
    environment: Literal["sandbox", "production"] = "sandbox"
    expires_in_days: int = Field(default=90, ge=1, le=365)


@router.post("/developer-credentials", status_code=201)
def create_platform_developer_credential(
    payload: DeveloperCredentialCreateIn,
    user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    organization = db.query(Organization).filter_by(
        id=payload.organization_id, is_active=True
    ).first()
    if not organization:
        raise HTTPException(404, "Active organization not found")
    credential_owner = db.query(Membership).join(User, User.id == Membership.user_id).filter(
        Membership.organization_id == organization.id, Membership.role == "org_admin",
        Membership.is_active.is_(True), User.is_active.is_(True),
    ).order_by(Membership.id.asc()).first()
    if not credential_owner:
        raise HTTPException(409, "Assign an active organization administrator before issuing developer credentials")
    raw_key = f"oc_{'live' if payload.environment == 'production' else 'test'}_{secrets.token_urlsafe(36)}"
    row = DeveloperApiKey(
        organization_id=organization.id,
        created_by_user_id=credential_owner.user_id,
        name=payload.name.strip(),
        key_prefix=raw_key[:16],
        secret_hash=hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
        scopes=["organization:read"],
        environment=payload.environment,
        expires_at=datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days),
    )
    db.add(row)
    db.flush()
    _audit(db, user, organization.id, "platform.developer_credential_created",
           "developer_api_key", row.id,
           f"prefix={row.key_prefix};environment={row.environment}")
    db.commit()
    db.refresh(row)
    # Secret is intentionally returned once only; it is never stored in plaintext.
    return {
        "id": row.id, "organization_id": row.organization_id, "name": row.name,
        "key_prefix": row.key_prefix, "environment": row.environment,
        "scopes": row.scopes, "expires_at": row.expires_at.isoformat(),
        "secret": raw_key,
    }


@router.get("/developer-credentials")
def list_platform_developer_credentials(
    organization_id: int | None = None,
    user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    query = db.query(DeveloperApiKey)
    if organization_id is not None:
        query = query.filter_by(organization_id=organization_id)
    rows = query.order_by(DeveloperApiKey.created_at.desc()).limit(500).all()
    counts = dict(db.query(DeveloperApiKeyUsage.api_key_id, func.count(DeveloperApiKeyUsage.id))
                  .filter(DeveloperApiKeyUsage.api_key_id.in_([row.id for row in rows]))
                  .group_by(DeveloperApiKeyUsage.api_key_id).all()) if rows else {}
    return [{
        "id": row.id, "organization_id": row.organization_id,
        "name": row.name, "key_prefix": row.key_prefix,
        "environment": row.environment, "scopes": row.scopes,
        "created_by_user_id": row.created_by_user_id,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "usage_count": counts.get(row.id, 0),
    } for row in rows]


@router.post("/developer-credentials/{credential_id}/revoke")
def revoke_platform_developer_credential(credential_id: int,
                                         user: User = Depends(require_platform_admin),
                                         db: Session = Depends(get_db)):
    row = db.query(DeveloperApiKey).filter_by(id=credential_id).with_for_update().first()
    if not row:
        raise HTTPException(404, "Developer credential not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        _audit(db, user, row.organization_id, "platform.developer_credential_revoked",
               "developer_api_key", row.id, f"prefix={row.key_prefix}")
        db.commit()
    return {"id": row.id, "revoked": True, "revoked_at": row.revoked_at.isoformat()}


class PlatformOperationIn(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    summary: str = Field(default="", max_length=4000)
    severity: Literal["info", "low", "medium", "high", "critical"] = "medium"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    affected_services: list[str] = Field(default_factory=list, max_length=30)
    owner: str = Field(default="", max_length=160)


class PlatformOperationTransitionIn(BaseModel):
    status: str = Field(min_length=3, max_length=32)
    note: str = Field(min_length=3, max_length=1000)


_OPERATION_STATES = {
    "incidents": {"draft", "investigating", "identified", "monitoring", "resolved", "closed"},
    "maintenance": {"draft", "scheduled", "in_progress", "completed", "cancelled"},
}


_OPERATION_TRANSITIONS = {
    "incidents": {
        "draft": {"investigating"},
        "investigating": {"identified"},
        "identified": {"monitoring"},
        "monitoring": {"resolved"},
        "resolved": {"closed"},
        "closed": set(),
    },
    "maintenance": {
        "draft": {"scheduled", "cancelled"},
        "scheduled": {"in_progress", "cancelled"},
        "in_progress": {"completed", "cancelled"},
        "completed": set(),
        "cancelled": set(),
    },
}


def _validate_operation_transition(kind: str, row, next_status: str, actor_id: int) -> None:
    current = row.status
    if next_status not in _OPERATION_STATES[kind]:
        raise HTTPException(422, "Unsupported operational status")
    if next_status not in _OPERATION_TRANSITIONS[kind].get(current, set()):
        raise HTTPException(409, f"Invalid {kind[:-1]} transition: {current} -> {next_status}")
    last_actor = (row.payload or {}).get("last_transition_by")
    maker_checker_states = {"scheduled", "in_progress", "resolved", "closed", "completed"}
    if next_status in maker_checker_states and actor_id in {row.owner_user_id, last_actor}:
        raise HTTPException(403, "A different platform administrator must approve this operational transition")


@router.get("/operations/readiness")
def platform_operational_readiness(
    user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """Expose safe configuration signals; never claim an unverified backup/restore."""
    try:
        db.execute(text("SELECT 1"))
        database_reachable = True
    except Exception:
        db.rollback()
        database_reachable = False
    backup_storage_keys = (
        "ONECORE_BACKUP_S3_BUCKET", "ONECORE_BACKUP_AWS_ACCESS_KEY_ID",
        "ONECORE_BACKUP_AWS_SECRET_ACCESS_KEY", "ONECORE_BACKUP_AWS_REGION",
    )
    configured_storage = [key for key in backup_storage_keys if os.getenv(key)]
    backup_database_configured = bool(
        os.getenv("ONECORE_BACKUP_DATABASE_URL") or os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    )
    restore_database_configured = bool(os.getenv("ONECORE_RESTORE_DATABASE_URL"))
    return {
        "database": {"configured": bool(os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")), "reachable": database_reachable},
        "backup": {
            "database_url_configured": backup_database_configured,
            "storage_configured": len(configured_storage) == len(backup_storage_keys),
            "storage_configuration_items_present": len(configured_storage),
            "storage_configuration_items_required": len(backup_storage_keys),
            "restore_target_configured": restore_database_configured,
            "evidence": "Runtime environment configuration only; this endpoint does not verify scheduled workflow secrets, backup artifacts, checksums or restore drills.",
        },
        "security": {
            "mfa_encryption_key_configured": bool(os.getenv("MFA_ENCRYPTION_KEY")),
            "production_mode": os.getenv("APP_ENV", "").lower() == "production",
        },
        "monitoring": {
            "healthcheck_url_configured": bool(os.getenv("ONECORE_HEALTHCHECK_URL")),
            "evidence": "The API runtime cannot inspect repository-level GitHub Actions secrets or monitoring run history.",
        },
    }


@router.get("/operations/{kind}")
def list_platform_operations(kind: Literal["incidents", "maintenance"],
                             user: User = Depends(require_platform_admin),
                             db: Session = Depends(get_db)):
    record_type = "incident" if kind == "incidents" else "maintenance"
    rows = db.query(PortalWorkflowRecord).filter_by(
        portal_key="operations", record_type=record_type
    ).order_by(PortalWorkflowRecord.created_at.desc()).limit(500).all()
    return [{"id": row.id, "status": row.status, "payload": row.payload or {},
             "created_by": row.owner_user_id, "created_at": row.created_at.isoformat(),
             "updated_at": row.updated_at.isoformat()} for row in rows]


@router.post("/operations/{kind}", status_code=201)
def create_platform_operation(kind: Literal["incidents", "maintenance"], payload: PlatformOperationIn,
                              user: User = Depends(require_platform_admin),
                              db: Session = Depends(get_db)):
    record_type = "incident" if kind == "incidents" else "maintenance"
    if payload.starts_at and payload.ends_at:
        starts = payload.starts_at.replace(tzinfo=timezone.utc) if payload.starts_at.tzinfo is None else payload.starts_at
        ends = payload.ends_at.replace(tzinfo=timezone.utc) if payload.ends_at.tzinfo is None else payload.ends_at
        if ends <= starts:
            raise HTTPException(422, "Operational end time must be after its start time")
    record = PortalWorkflowRecord(
        portal_key="operations", record_type=record_type, organization_id=None,
        owner_user_id=user.id, visibility="private", status="draft",
        payload=payload.model_dump(mode="json"),
    )
    db.add(record)
    db.flush()
    _audit(db, user, None, f"platform.{record_type}_created", record_type, record.id, payload.title)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "status": record.status, "payload": record.payload}


@router.post("/operations/{kind}/{record_id}/transition")
def transition_platform_operation(kind: Literal["incidents", "maintenance"], record_id: int,
                                  payload: PlatformOperationTransitionIn,
                                  user: User = Depends(require_platform_admin),
                                  db: Session = Depends(get_db)):
    record_type = "incident" if kind == "incidents" else "maintenance"
    row = db.query(PortalWorkflowRecord).filter_by(
        id=record_id, portal_key="operations", record_type=record_type
    ).with_for_update().first()
    if not row:
        raise HTTPException(404, "Operational record not found")
    _validate_operation_transition(kind, row, payload.status, user.id)
    previous = row.status
    row.status = payload.status
    row.payload = {**(row.payload or {}), "last_transition_note": payload.note,
                   "last_transition_by": user.id, "last_transition_at": datetime.now(timezone.utc).isoformat()}
    _audit(db, user, None, f"platform.{record_type}_transitioned", record_type, row.id,
           f"{previous}->{payload.status};{payload.note.strip()}")
    db.commit()
    return {"id": row.id, "status": row.status, "payload": row.payload}


@router.post("/users/{user_id}/revoke-sessions")
def revoke_platform_user_sessions(user_id: int, reason: str = Query(min_length=3, max_length=500),
                                  user: User = Depends(require_platform_admin),
                                  db: Session = Depends(get_db)):
    row = db.query(User).filter_by(id=user_id).with_for_update().first()
    if not row:
        raise HTTPException(404, "User not found")
    if row.platform_role == "root_superadmin":
        raise HTTPException(403, "Root Superadmin sessions cannot be revoked through this endpoint")
    row.auth_version = int(row.auth_version or 0) + 1
    _audit(db, user, None, "platform.user_sessions_revoked", "user", row.id, reason.strip())
    db.commit()
    return {"user_id": row.id, "sessions_revoked": True}
