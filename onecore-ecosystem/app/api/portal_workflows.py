"""Shared public-content and authenticated workspace APIs for OneCore portals.

Public content is explicitly published by a platform administrator. Private
resources are always scoped to the signed-in owner and, when supplied, an
active organization membership. Browser visibility is never an authorization
boundary: every read and write is checked here.
"""
from datetime import datetime, timezone
import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.authorization import require_permission
from app.core.database import get_db
from app.core.models import AuditEvent, Membership, Organization, PortalPublicContent, PortalResource, User
from app.core.security import current_user

router = APIRouter(prefix="/api/v1/portals", tags=["public-portals"])

PORTALS = {
    "support": {"help_article", "faq", "announcement"},
    "status": {"incident", "maintenance", "component", "alert_subscription", "notification_preference"},
    "developers": {"api_reference", "integration_guide", "api_application", "api_key", "webhook", "sandbox"},
    "docs": {"guide", "module_guide", "role_instruction", "bookmark"},
    "community": {"post", "comment", "group_membership", "profile"},
    "trust": {"security_policy", "compliance", "disclosure", "security_report", "security_case", "authorized_document"},
    "events": {"event", "event_registration", "booking", "event_material"},
    "careers": {"vacancy", "applicant_profile", "job_application"},
    "partners": {"programme", "opportunity", "partner_profile", "referral", "lead", "agreement", "partner_resource"},
}
ORG_SHARED_KINDS = {
    "alert_subscription", "notification_preference", "api_application", "webhook",
    "sandbox", "module_guide", "role_instruction", "group_membership",
    "authorized_document", "event_registration", "booking", "event_material",
    "partner_profile", "referral", "lead", "agreement", "partner_resource",
}
SENSITIVE_KINDS = {"api_key", "security_report", "security_case", "job_application", "agreement"}
FORBIDDEN_SECRET_KEYS = {
    "secret", "client_secret", "password", "private_key", "access_token",
    "refresh_token", "api_secret", "service_role_key", "database_url",
}

class PublicContentIn(BaseModel):
    portal: str = Field(min_length=2, max_length=32)
    content_type: str = Field(min_length=2, max_length=48)
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str = Field(min_length=2, max_length=180)
    summary: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=50000)
    metadata: dict = Field(default_factory=dict)
    status: str = Field(default="draft", pattern=r"^(draft|published|archived)$")

class PortalResourceIn(BaseModel):
    kind: str = Field(min_length=2, max_length=48)
    data: dict = Field(default_factory=dict)
    organization_id: int | None = Field(default=None, gt=0)
    visibility: str = Field(default="private", pattern=r"^(private|organization)$")

class PortalResourcePatch(BaseModel):
    data: dict | None = None
    visibility: str | None = Field(default=None, pattern=r"^(private|organization)$")

def _now():
    return datetime.now(timezone.utc)

def _validate_portal(portal: str):
    if portal not in PORTALS:
        raise HTTPException(404, "Unknown OneCore application")
    return portal

def _validate_data(data: dict):
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).lower()
                if normalized in FORBIDDEN_SECRET_KEYS or (normalized.endswith("_secret") and normalized != "secret_manager_ref"):
                    raise HTTPException(422, "Credential material cannot be stored in portal resource data")
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(data)

def _membership(db: Session, user: User, organization_id: int):
    membership = db.query(Membership).filter_by(
        user_id=user.id, organization_id=organization_id, is_active=True
    ).first()
    organization = db.query(Organization).filter_by(id=organization_id, is_active=True).first()
    if not membership or not organization:
        raise HTTPException(404, "Organization not found")
    return membership

def _is_org_admin(membership):
    return (membership.role or "").lower() in {"org_admin", "school_admin", "security_admin", "partner_admin"}

def _audit(db, user_id, org_id, action, kind, resource_id, detail=""):
    db.add(AuditEvent(actor_user_id=user_id, organization_id=org_id,
        action=action, resource_type=f"portal:{kind}", resource_id=str(resource_id), detail=detail[:1000]))

def _resource_out(row, include_secret=False):
    data = dict(row.data or {})
    one_time_secret = data.pop("_one_time_secret", None)
    result = {"id": row.id, "portal": row.portal_key, "kind": row.resource_kind,
        "organization_id": row.organization_id, "owner_user_id": row.owner_user_id,
        "visibility": row.visibility, "data": data, "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat()}
    if include_secret and one_time_secret:
        result["secret"] = one_time_secret
    return result

@router.get("/{portal}/content")
def list_public_content(portal: str, content_type: str | None = None,
                        limit: int = Query(default=50, ge=1, le=100),
                        db: Session = Depends(get_db)):
    """Anonymous, published-only content. No private records are queried here."""
    _validate_portal(portal)
    query = db.query(PortalPublicContent).filter_by(portal_key=portal, status="published")
    if content_type:
        query = query.filter_by(content_type=content_type)
    rows = query.order_by(PortalPublicContent.published_at.desc(), PortalPublicContent.id.desc()).limit(limit).all()
    return [{"id": row.id, "portal": row.portal_key, "content_type": row.content_type,
        "slug": row.slug, "title": row.title, "summary": row.summary, "body": row.body,
        "metadata": row.metadata_json or {},
        "published_at": row.published_at.isoformat() if row.published_at else None} for row in rows]

@router.get("/{portal}/content/{slug}")
def get_public_content(portal: str, slug: str, db: Session = Depends(get_db)):
    _validate_portal(portal)
    row = db.query(PortalPublicContent).filter_by(
        portal_key=portal, slug=slug, status="published"
    ).first()
    if not row:
        raise HTTPException(404, "Public content not found")
    return {"id": row.id, "portal": row.portal_key, "content_type": row.content_type,
        "slug": row.slug, "title": row.title, "summary": row.summary, "body": row.body,
        "metadata": row.metadata_json or {}, "published_at": row.published_at.isoformat() if row.published_at else None}

@router.post("/content", status_code=201)
def publish_portal_content(payload: PublicContentIn, user: User = Depends(current_user),
                           db: Session = Depends(get_db)):
    if user.platform_role not in {"root_superadmin", "platform_admin"}:
        raise HTTPException(403, "Platform administrator access is required")
    _validate_portal(payload.portal)
    public_types = {
        "support": {"help_article", "faq", "announcement"},
        "status": {"incident", "maintenance", "component", "announcement"},
        "developers": {"api_reference", "integration_guide"},
        "docs": {"guide", "announcement"},
        "community": {"post", "announcement"},
        "trust": {"security_policy", "compliance", "disclosure"},
        "events": {"event", "announcement"},
        "careers": {"vacancy", "announcement"},
        "partners": {"programme", "opportunity", "announcement"},
    }
    if payload.content_type not in public_types[payload.portal]:
        raise HTTPException(422, "Unsupported public content type for this portal")
    _validate_data(payload.metadata)
    row = db.query(PortalPublicContent).filter_by(
        portal_key=payload.portal, slug=payload.slug
    ).first()
    if row:
        raise HTTPException(409, "A content item with this slug already exists")
    row = PortalPublicContent(portal_key=payload.portal, content_type=payload.content_type,
        slug=payload.slug, title=payload.title, summary=payload.summary, body=payload.body,
        metadata_json=payload.metadata, status=payload.status,
        published_at=_now() if payload.status == "published" else None, created_by=user.id)
    db.add(row)
    db.flush()
    _audit(db, user.id, None, "portal.public_content.created", payload.content_type, row.id, payload.slug)
    db.commit()
    return {"id": row.id, "portal": row.portal_key, "slug": row.slug, "status": row.status}

@router.patch("/content/{content_id}")
def update_portal_content(content_id: int, payload: PublicContentIn,
                          user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.platform_role not in {"root_superadmin", "platform_admin"}:
        raise HTTPException(403, "Platform administrator access is required")
    row = db.query(PortalPublicContent).filter_by(id=content_id).with_for_update().first()
    if not row:
        raise HTTPException(404, "Content not found")
    _validate_portal(payload.portal)
    _validate_data(payload.metadata)
    row.portal_key, row.content_type, row.slug = payload.portal, payload.content_type, payload.slug
    row.title, row.summary, row.body = payload.title, payload.summary, payload.body
    row.metadata_json, row.status = payload.metadata, payload.status
    row.published_at = _now() if payload.status == "published" else None
    _audit(db, user.id, None, "portal.public_content.updated", payload.content_type, row.id, payload.slug)
    db.commit()
    return {"id": row.id, "status": row.status}

@router.get("/{portal}/resources")
def list_portal_resources(portal: str, kind: str | None = None,
                          organization_id: int | None = Query(default=None, gt=0),
                          user: User = Depends(current_user), db: Session = Depends(get_db)):
    _validate_portal(portal)
    allowed = PORTALS[portal]
    if kind and kind not in allowed:
        raise HTTPException(404, "Unsupported resource type for this application")
    query = db.query(PortalResource).filter_by(portal_key=portal, owner_user_id=user.id)
    if organization_id is not None:
        membership = _membership(db, user, organization_id)
        require_permission(membership, "read")
        query = db.query(PortalResource).filter(
            PortalResource.portal_key == portal,
            PortalResource.organization_id == organization_id,
            or_(PortalResource.owner_user_id == user.id,
                PortalResource.visibility == "organization")
        )
    else:
        query = query.filter(PortalResource.organization_id.is_(None))
    if kind:
        query = query.filter_by(resource_kind=kind)
    rows = query.order_by(PortalResource.updated_at.desc()).limit(200).all()
    return [_resource_out(row) for row in rows]

@router.post("/{portal}/resources", status_code=201)
def create_portal_resource(portal: str, payload: PortalResourceIn,
                           user: User = Depends(current_user), db: Session = Depends(get_db)):
    _validate_portal(portal)
    if payload.kind not in PORTALS[portal]:
        raise HTTPException(404, "Unsupported resource type for this application")
    _validate_data(payload.data)
    membership = None
    if payload.organization_id is not None:
        membership = _membership(db, user, payload.organization_id)
        require_permission(membership, "create")
    if payload.visibility == "organization":
        if membership is None or not _is_org_admin(membership):
            raise HTTPException(403, "Organization administrator access is required for shared resources")
        if payload.kind in SENSITIVE_KINDS:
            raise HTTPException(422, "Sensitive resources must remain private to their owner")
    data = dict(payload.data)
    response_secret = None
    if portal == "developers" and payload.kind == "api_key":
        response_secret = "oc_live_" + secrets.token_urlsafe(32)
        data["secret_hash"] = hashlib.sha256(response_secret.encode()).hexdigest()
        data["secret_prefix"] = response_secret[:14]
        data["status"] = "active"
        data["last_used_at"] = None
    if portal == "developers" and payload.kind == "webhook":
        response_secret = "ocwhsec_" + secrets.token_urlsafe(32)
        data["secret_hash"] = hashlib.sha256(response_secret.encode()).hexdigest()
        data["secret_prefix"] = response_secret[:14]
        data["status"] = "pending"
    if portal == "trust" and payload.kind in {"security_report", "security_case"}:
        data["confidential"] = True
        data["status"] = data.get("status", "submitted")
    row = PortalResource(portal_key=portal, resource_kind=payload.kind,
        organization_id=payload.organization_id, owner_user_id=user.id,
        visibility=payload.visibility, data=data)
    db.add(row)
    db.flush()
    _audit(db, user.id, payload.organization_id, f"portal.{portal}.{payload.kind}.created",
        payload.kind, row.id)
    db.commit()
    result = _resource_out(row)
    if response_secret:
        result["secret"] = response_secret
        result["secret_warning"] = "Shown once. Copy it now; it cannot be retrieved again."
    return result

@router.get("/{portal}/resources/{resource_id}")
def get_portal_resource(portal: str, resource_id: int,
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    _validate_portal(portal)
    row = db.query(PortalResource).filter_by(id=resource_id, portal_key=portal).first()
    if not row:
        raise HTTPException(404, "Resource not found")
    if row.organization_id is None:
        if row.owner_user_id != user.id:
            raise HTTPException(404, "Resource not found")
    else:
        membership = _membership(db, user, row.organization_id)
        if row.owner_user_id != user.id and (row.visibility != "organization" or not membership):
            raise HTTPException(404, "Resource not found")
        require_permission(membership, "read")
        if portal == "trust" and row.resource_kind in {"security_report", "security_case"}:
            if row.owner_user_id != user.id and not _is_org_admin(membership):
                raise HTTPException(404, "Resource not found")
    return _resource_out(row)

@router.patch("/{portal}/resources/{resource_id}")
def update_portal_resource(portal: str, resource_id: int, payload: PortalResourcePatch,
                           user: User = Depends(current_user), db: Session = Depends(get_db)):
    _validate_portal(portal)
    row = db.query(PortalResource).filter_by(id=resource_id, portal_key=portal).with_for_update().first()
    if not row:
        raise HTTPException(404, "Resource not found")
    if row.organization_id is not None:
        membership = _membership(db, user, row.organization_id)
        require_permission(membership, "update")
        if row.owner_user_id != user.id and not (_is_org_admin(membership) and row.visibility == "organization"):
            raise HTTPException(404, "Resource not found")
    elif row.owner_user_id != user.id:
        raise HTTPException(404, "Resource not found")
    if payload.data is not None:
        _validate_data(payload.data)
        # Credential hashes, owner IDs, and workflow status are immutable through generic patch.
        for key in ("secret_hash", "secret_prefix", "owner_user_id", "status", "confidential"):
            if key in payload.data:
                raise HTTPException(422, f"{key} cannot be changed through this endpoint")
        row.data = {**(row.data or {}), **payload.data}
    if payload.visibility is not None:
        if row.organization_id is None or payload.visibility == "organization":
            if row.organization_id is None:
                raise HTTPException(422, "Personal resources cannot be organization-visible")
            if not _is_org_admin(membership):
                raise HTTPException(403, "Organization administrator access is required")
        row.visibility = payload.visibility
    _audit(db, user.id, row.organization_id, f"portal.{portal}.{row.resource_kind}.updated",
        row.resource_kind, row.id)
    db.commit()
    return _resource_out(row)

@router.delete("/{portal}/resources/{resource_id}", status_code=204)
def delete_portal_resource(portal: str, resource_id: int,
                           user: User = Depends(current_user), db: Session = Depends(get_db)):
    _validate_portal(portal)
    row = db.query(PortalResource).filter_by(id=resource_id, portal_key=portal).with_for_update().first()
    if not row:
        raise HTTPException(404, "Resource not found")
    if row.organization_id is not None:
        membership = _membership(db, user, row.organization_id)
        require_permission(membership, "delete")
        if row.owner_user_id != user.id and not _is_org_admin(membership):
            raise HTTPException(404, "Resource not found")
    elif row.owner_user_id != user.id:
        raise HTTPException(404, "Resource not found")
    _audit(db, user.id, row.organization_id, f"portal.{portal}.{row.resource_kind}.deleted",
        row.resource_kind, row.id)
    db.delete(row)
    db.commit()
    return None
