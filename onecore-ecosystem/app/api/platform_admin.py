"""Restricted OneCore platform administration APIs."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import AuditEvent, Membership, Organization, User
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
    amount: float = Field(ge=0, le=100000000)
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
