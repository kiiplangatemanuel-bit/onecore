"""Shared public/private workflows for independently deployed OneCore portals.

Public reads are anonymous and strictly limited to published public resources.
All writes and private reads require an active OneCore identity and, for tenant
resources, an active organization membership plus a role permission.
"""
import json
import secrets
import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import AuditEvent, Membership, User
from app.core.portal_models import PortalResource
from app.core.security import current_user, require_platform_admin
from app.core.authorization import require_permission

router = APIRouter(prefix="/api/v1/portals", tags=["portal-access"])

PORTALS = {
    "support": {"help_article", "faq", "announcement", "enquiry"},
    "status": {"incident", "maintenance", "alert_subscription"},
    "developers": {"guide", "application", "api_key", "webhook", "sandbox"},
    "docs": {"guide", "module_guide", "bookmark", "guide_feedback"},
    "community": {"announcement", "post", "comment", "group_membership"},
    "trust": {"policy", "disclosure", "security_report", "document_access_request"},
    "events": {"event", "webinar", "event_registration"},
    "careers": {"vacancy", "company_page", "applicant_profile", "job_application"},
    "partners": {"programme", "partner_profile", "referral", "lead", "agreement_access"},
}
SENSITIVE_TYPES = {"security_report", "document_access_request"}
PLATFORM_ONLY_TYPES = {"incident", "maintenance", "help_article", "faq", "guide", "module_guide", "policy", "disclosure", "event", "webinar", "vacancy", "company_page", "programme", "announcement"}
STATUS_TRANSITIONS = {
    "incident": {"published", "investigating", "resolved", "archived"},
    "maintenance": {"published", "scheduled", "in_progress", "completed", "archived"},
    "help_article": {"published", "archived"},
    "faq": {"published", "archived"},
    "guide": {"published", "archived"},
    "module_guide": {"published", "archived"},
    "policy": {"published", "archived"},
    "disclosure": {"published", "archived"},
    "event": {"published", "archived"},
    "webinar": {"published", "archived"},
    "vacancy": {"published", "closed", "archived"},
    "company_page": {"published", "archived"},
    "programme": {"published", "archived"},
    "announcement": {"published", "archived"},
    "alert_subscription": {"active", "paused", "cancelled"},
    "application": {"active", "suspended", "revoked"},
    "api_key": {"active", "revoked"},
    "webhook": {"active", "disabled"},
    "sandbox": {"active", "disabled"},
    "bookmark": {"active", "archived"},
    "guide_feedback": {"submitted", "reviewed", "withdrawn"},
    "post": {"pending_review", "published", "archived"},
    "comment": {"pending_review", "published", "archived"},
    "group_membership": {"active", "left"},
    "security_report": {"submitted", "under_review", "resolved", "closed", "withdrawn"},
    "document_access_request": {"submitted", "approved", "rejected", "withdrawn"},
    "event_registration": {"registered", "waitlisted", "cancelled", "attended"},
    "applicant_profile": {"active", "withdrawn"},
    "job_application": {"submitted", "under_review", "interview", "offered", "rejected", "withdrawn"},
    "partner_profile": {"pending_review", "active", "suspended"},
    "referral": {"submitted", "qualified", "accepted", "rejected", "paid"},
    "lead": {"submitted", "qualified", "accepted", "rejected", "converted"},
    "agreement_access": {"requested", "granted", "revoked"},
}

class PortalItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_type: str = Field(min_length=2, max_length=48)
    title: str = Field(min_length=2, max_length=200)
    body: str = Field(default="", max_length=20000)
    data: dict = Field(default_factory=dict)
    organization_id: int | None = Field(default=None, gt=0)
    visibility: str | None = Field(default=None, pattern=r"^(private|organization|public)$")

class PortalItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=2, max_length=200)
    body: str | None = Field(default=None, max_length=20000)
    data: dict | None = None
    status: str | None = Field(default=None, min_length=2, max_length=24)
    visibility: str | None = Field(default=None, pattern=r"^(private|organization|public)$")

def _validate_portal(portal: str):
    if portal not in PORTALS:
        raise HTTPException(404, "OneCore portal not found")

def _membership(db: Session, user: User, organization_id: int):
    membership = db.query(Membership).filter_by(
        user_id=user.id, organization_id=organization_id, is_active=True
    ).first()
    if not membership:
        raise HTTPException(403, "Active membership in this organization is required")
    return membership

def _out(row: PortalResource):
    data = dict(row.data or {})
    data.pop("_credential_hash", None)
    data.pop("_credential_prefix", None)
    return {
        "id": row.id, "portal": row.portal, "resource_type": row.resource_type,
        "visibility": row.visibility, "title": row.title, "body": row.body,
        "data": data, "status": row.status, "owner_user_id": row.owner_user_id,
        "organization_id": row.organization_id,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
    }

def _audit(db: Session, user: User, organization_id: int | None, action: str, row: PortalResource):
    db.add(AuditEvent(
        actor_user_id=user.id, organization_id=organization_id, action=action,
        resource_type=f"{row.portal}.{row.resource_type}", resource_id=str(row.id),
    ))

@router.get("/{portal}/public")
def list_public_resources(
    portal: str, resource_type: str | None = Query(default=None, max_length=48),
    limit: int = Query(default=50, ge=1, le=100), db: Session = Depends(get_db),
):
    _validate_portal(portal)
    query = db.query(PortalResource).filter_by(
        portal=portal, visibility="public", status="published"
    )
    if resource_type:
        if resource_type not in PORTALS[portal]:
            raise HTTPException(400, "Resource type is not supported by this portal")
        query = query.filter_by(resource_type=resource_type)
    rows = query.order_by(PortalResource.updated_at.desc(), PortalResource.id.desc()).limit(limit).all()
    return [_out(row) for row in rows]

@router.get("/{portal}/me")
def list_my_resources(
    portal: str, organization_id: int | None = Query(default=None, gt=0),
    resource_type: str | None = Query(default=None, max_length=48),
    limit: int = Query(default=100, ge=1, le=200),
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    _validate_portal(portal)
    query = db.query(PortalResource).filter(PortalResource.portal == portal)
    if organization_id is not None:
        membership = _membership(db, user, organization_id)
        query = query.filter(or_(
            (PortalResource.owner_user_id == user.id) & (PortalResource.organization_id.is_(None)),
            (PortalResource.organization_id == membership.organization_id) & (PortalResource.visibility == "organization"),
        ))
    else:
        org_ids = [m.organization_id for m in db.query(Membership).filter_by(
            user_id=user.id, is_active=True
        ).all()]
        query = query.filter(or_(
            (PortalResource.owner_user_id == user.id) & (PortalResource.organization_id.is_(None)),
            (PortalResource.organization_id.in_(org_ids) & (PortalResource.visibility == "organization")) if org_ids else False,
        ))
    if resource_type:
        if resource_type not in PORTALS[portal]:
            raise HTTPException(400, "Resource type is not supported by this portal")
        query = query.filter_by(resource_type=resource_type)
    rows = query.order_by(PortalResource.updated_at.desc(), PortalResource.id.desc()).limit(limit).all()
    return [_out(row) for row in rows]

@router.post("/{portal}/items", status_code=201)
def create_portal_resource(
    portal: str, payload: PortalItemIn,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    _validate_portal(portal)
    if payload.resource_type not in PORTALS[portal]:
        raise HTTPException(400, "Resource type is not supported by this portal")
    if payload.resource_type in PLATFORM_ONLY_TYPES and user.platform_role not in {"root_superadmin", "platform_admin"}:
        raise HTTPException(403, "This resource type is managed by authorized OneCore staff")
    if len(json.dumps(payload.data, ensure_ascii=False)) > 30000:
        raise HTTPException(413, "Portal resource data exceeds the 30 KB limit")
    org_id = payload.organization_id
    if org_id is not None:
        membership = _membership(db, user, org_id)
        require_permission(membership, "create")
    visibility = payload.visibility or ("organization" if org_id is not None else "private")
    if payload.resource_type in SENSITIVE_TYPES and (org_id is not None or visibility != "private"):
        raise HTTPException(422, "Confidential trust reports must be submitted as personal, owner-only records")
    if visibility == "public" and user.platform_role not in {"root_superadmin", "platform_admin"}:
        raise HTTPException(403, "Only authorized OneCore staff can publish portal resources")
    if visibility == "organization" and org_id is None:
        raise HTTPException(422, "Organization visibility requires an organization membership")
    if payload.resource_type == "api_key" and org_id is not None and membership.role != "org_admin":
        raise HTTPException(403, "Only an organization administrator can create organization API keys")
    data = dict(payload.data)
    initial_status = {
        "post": "pending_review", "comment": "pending_review",
        "security_report": "submitted", "document_access_request": "submitted",
        "event_registration": "registered", "job_application": "submitted",
        "alert_subscription": "active", "bookmark": "active",
        "api_key": "active", "application": "active", "webhook": "active",
        "sandbox": "active", "applicant_profile": "active",
        "partner_profile": "pending_review", "referral": "submitted",
        "lead": "submitted", "agreement_access": "requested",
        "group_membership": "active", "guide_feedback": "submitted",
    }.get(payload.resource_type, "active")
    one_time_secret = None
    if payload.resource_type == "api_key":
        one_time_secret = "oc_live_" + secrets.token_urlsafe(36)
        data["_credential_hash"] = hashlib.sha256(one_time_secret.encode()).hexdigest()
        data["_credential_prefix"] = one_time_secret[:15]
    row = PortalResource(
        portal=portal, resource_type=payload.resource_type,
        visibility=visibility, title=payload.title.strip(), body=payload.body.strip(),
        data=data, status=initial_status, owner_user_id=user.id, organization_id=org_id,
    )
    db.add(row)
    db.flush()
    _audit(db, user, org_id, f"{portal}.{payload.resource_type}.created", row)
    db.commit()
    db.refresh(row)
    result = _out(row)
    if one_time_secret:
        result["one_time_secret"] = one_time_secret
    return result

@router.patch("/{portal}/items/{item_id}")
def update_portal_resource(
    portal: str, item_id: int, payload: PortalItemUpdate,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    _validate_portal(portal)
    row = db.query(PortalResource).filter_by(id=item_id, portal=portal).first()
    if not row:
        raise HTTPException(404, "Portal resource not found")
    is_platform_admin = user.platform_role in {"root_superadmin", "platform_admin"}
    if row.resource_type in SENSITIVE_TYPES:
        allowed = row.owner_user_id == user.id or is_platform_admin
    elif row.organization_id is not None:
        membership = _membership(db, user, row.organization_id)
        allowed = row.owner_user_id == user.id or (row.visibility == "organization" and membership.role == "org_admin")
    else:
        allowed = row.owner_user_id == user.id or (is_platform_admin and row.resource_type in PLATFORM_ONLY_TYPES)
    if not allowed:
        raise HTTPException(404, "Portal resource not found")
    if payload.data is not None:
        if len(json.dumps(payload.data, ensure_ascii=False)) > 30000:
            raise HTTPException(413, "Portal resource data exceeds the 30 KB limit")
        # Internal credential digests are immutable and never replaceable through this API.
        if "_credential_hash" in payload.data or "_credential_prefix" in payload.data:
            raise HTTPException(422, "Credential metadata cannot be modified")
        row.data = {**(row.data or {}), **payload.data}
    if payload.title is not None:
        row.title = payload.title.strip()
    if payload.body is not None:
        row.body = payload.body.strip()
    if payload.visibility is not None:
        if row.resource_type in SENSITIVE_TYPES and payload.visibility != "private":
            raise HTTPException(422, "Confidential trust records cannot be published")
        if payload.visibility != "private" and not is_platform_admin:
            raise HTTPException(403, "Only authorized OneCore staff can change resource visibility")
        if payload.visibility == "organization" and row.organization_id is None:
            raise HTTPException(422, "Organization visibility requires an organization-owned resource")
        row.visibility = payload.visibility
    if payload.status is not None:
        allowed_statuses = STATUS_TRANSITIONS.get(row.resource_type, {"active", "archived"})
        if payload.status not in allowed_statuses:
            raise HTTPException(422, "Invalid status transition for this resource")
        if row.resource_type in SENSITIVE_TYPES and not is_platform_admin and payload.status not in {"withdrawn"}:
            raise HTTPException(403, "Only authorized security staff can change confidential report status")
        if row.resource_type in {"post", "comment"} and payload.status == "published" and not is_platform_admin:
            raise HTTPException(403, "Community content must be approved by a moderator")
        row.status = payload.status
    row.updated_at = datetime.now(timezone.utc)
    _audit(db, user, row.organization_id, f"{portal}.{row.resource_type}.updated", row)
    db.commit()
    db.refresh(row)
    return _out(row)

@router.get("/{portal}/admin")
def list_portal_admin_resources(
    portal: str, status: str | None = Query(default=None, max_length=24),
    limit: int = Query(default=100, ge=1, le=250),
    user: User = Depends(require_platform_admin), db: Session = Depends(get_db),
):
    """Moderation and publication queue; never available to ordinary members."""
    _validate_portal(portal)
    query = db.query(PortalResource).filter_by(portal=portal)
    if status:
        query = query.filter_by(status=status)
    rows = query.order_by(PortalResource.updated_at.asc(), PortalResource.id.asc()).limit(limit).all()
    return [_out(row) for row in rows]

@router.get("/{portal}/items/{item_id}")
def read_my_resource(
    portal: str, item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db),
):
    _validate_portal(portal)
    row = db.query(PortalResource).filter_by(id=item_id, portal=portal).first()
    if not row:
        raise HTTPException(404, "Portal resource not found")
    if row.visibility == "public" and row.status == "published":
        return _out(row)
    if row.organization_id is None and row.owner_user_id == user.id:
        return _out(row)
    if row.organization_id is not None and row.visibility == "organization":
        try:
            _membership(db, user, row.organization_id)
            return _out(row)
        except HTTPException:
            pass
    elif row.organization_id is not None and row.owner_user_id == user.id:
        try:
            _membership(db, user, row.organization_id)
            return _out(row)
        except HTTPException:
            pass
    if row.resource_type in SENSITIVE_TYPES and user.platform_role in {"root_superadmin", "platform_admin"}:
        return _out(row)
    raise HTTPException(404, "Portal resource not found")
