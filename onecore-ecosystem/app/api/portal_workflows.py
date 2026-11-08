"""Tenant-safe data workflows shared by the independently deployed OneCore portals.

The portal name and resource type are allow-listed here; clients cannot choose
arbitrary tables or modules. Public reads return published public records only.
All private operations require a live OneCore identity and verified membership.
"""
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session
from cryptography.fernet import Fernet, InvalidToken
import base64
import hashlib
import json

from app.core.config import settings

from app.core.database import get_db
from app.core.models import AuditEvent, Membership, Organization, PortalResource, User
from app.core.security import current_user, require_platform_admin
from app.core.authorization import require_permission

router = APIRouter(prefix="/api/v1/portals", tags=["public and authenticated portals"])

PORTAL_TYPES = {
    "status": {"alert_subscription", "organization_service"},
    "developers": {"application", "webhook", "sandbox", "usage_access"},
    "docs": {"private_guide"},
    "community": {"post", "comment", "group", "profile"},
    "trust": {"security_report", "security_case", "authorized_document"},
    "events": {"registration", "booking", "attendee_material", "attendance"},
    "careers": {"applicant_profile", "application"},
    "partners": {"partner_profile", "referral", "lead", "agreement", "partner_resource"},
}
PUBLIC_TYPES = {
    "status": {"incident", "maintenance"},
    "developers": {"api_guide", "example"},
    "docs": {"guide", "release_note"},
    "community": {"announcement", "discussion"},
    "trust": {"security_policy", "compliance_disclosure", "advisory"},
    "events": {"event", "webinar", "announcement"},
    "careers": {"vacancy", "company_information"},
    "partners": {"opportunity", "programme", "public_resource"},
}
SENSITIVE_TYPES = {"security_report", "security_case", "authorized_document", "agreement"}
ROLE_GATED_TYPES = {
    "application": {"org_admin", "developer_admin", "developer_manager", "developer"},
    "webhook": {"org_admin", "developer_admin", "developer_manager", "developer"},
    "sandbox": {"org_admin", "developer_admin", "developer_manager", "developer"},
    "usage_access": {"org_admin", "developer_admin", "developer_manager", "developer"},
    "organization_service": {"org_admin", "branch_admin", "manager"},
    "alert_subscription": {"org_admin", "manager"},
    "partner_profile": {"org_admin", "partner_admin", "partner_manager"},
    "referral": {"org_admin", "partner_admin", "partner_manager"},
    "lead": {"org_admin", "partner_admin", "partner_manager"},
    "agreement": {"org_admin", "partner_admin"},
    "partner_resource": {"org_admin", "partner_admin", "partner_manager"},
    "attendee_material": {"org_admin", "event_manager"},
    "attendance": {"org_admin", "event_manager"},
    "security_report": {"org_admin", "security_admin", "compliance_officer"},
    "security_case": {"org_admin", "security_admin", "compliance_officer"},
    "authorized_document": {"org_admin", "security_admin", "compliance_officer"},
}
MAX_PAGE_SIZE = 100


class PortalResourceIn(BaseModel):
    resource_type: str = Field(min_length=2, max_length=48, pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=2, max_length=180)
    summary: str = Field(default="", max_length=500)
    data: dict[str, Any] = Field(default_factory=dict)
    organization_id: int | None = Field(default=None, gt=0)


class PortalResourceUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=180)
    summary: str | None = Field(default=None, max_length=500)
    data: dict[str, Any] | None = None


def _portal(portal: str) -> str:
    if portal not in PORTAL_TYPES:
        raise HTTPException(404, "Portal not found")
    return portal


def _membership(db: Session, user: User, organization_id: int) -> Membership:
    membership = db.query(Membership).filter_by(
        user_id=user.id, organization_id=organization_id, is_active=True
    ).first()
    organization = db.query(Organization).filter_by(id=organization_id, is_active=True).first()
    if not membership or not organization:
        raise HTTPException(404, "Organization resource not found")
    return membership


def _visible_resource(db: Session, user: User, resource: PortalResource) -> Membership | None:
    # Re-check membership even for the creator: revocation must revoke tenant access.
    if resource.organization_id is not None:
        membership = _membership(db, user, resource.organization_id)
        if not _role_allowed(resource, user, membership):
            raise HTTPException(404, "Portal resource not found")
        return membership
    if resource.owner_user_id != user.id:
        raise HTTPException(404, "Portal resource not found")
    return None


def _role_allowed(row: PortalResource, user: User, membership: Membership | None) -> bool:
    if row.owner_user_id == user.id:
        return True
    if row.organization_id is None:
        return False
    required = ROLE_GATED_TYPES.get(row.resource_type)
    return not required or bool(membership and membership.role in required)


def _fernet() -> Fernet:
    # Derived from server-only SECRET_KEY; key rotation needs a re-encryption migration.
    digest = hashlib.sha256((settings.secret_key + ":portal-sensitive-data:v1").encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _stored_payload(resource_type: str, data: dict) -> tuple[dict, str | None]:
    if resource_type in SENSITIVE_TYPES:
        token = _fernet().encrypt(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()).decode()
        return {}, token
    return data, None


def _read_payload(row: PortalResource) -> dict:
    if not row.encrypted_payload:
        return row.data or {}
    try:
        return json.loads(_fernet().decrypt(row.encrypted_payload.encode()).decode())
    except (InvalidToken, ValueError, TypeError):
        raise HTTPException(503, "Confidential portal data could not be decrypted; contact the platform administrator")


def _out(row: PortalResource) -> dict:
    return {
        "id": row.id, "portal": row.portal, "resource_type": row.resource_type,
        "title": row.title, "summary": row.summary, "data": _read_payload(row),
        "organization_id": row.organization_id, "owner_user_id": row.owner_user_id,
        "visibility": row.visibility, "status": row.status,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
    }


def _audit(db: Session, user: User, row: PortalResource, action: str, detail: str = "") -> None:
    db.add(AuditEvent(
        organization_id=row.organization_id, actor_user_id=user.id, action=action,
        resource_type="portal_resource", resource_id=str(row.id),
        detail=f"portal={row.portal};type={row.resource_type};{detail}"[:1000],
    ))


@router.get("/{portal}/public")
def list_public_resources(
    portal: str,
    resource_type: str | None = Query(default=None, min_length=2, max_length=48),
    limit: int = Query(default=30, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    portal = _portal(portal)
    allowed = PUBLIC_TYPES[portal]
    if resource_type and resource_type not in allowed:
        raise HTTPException(404, "Public resource type not found")
    query = db.query(PortalResource).filter(
        PortalResource.portal == portal,
        PortalResource.resource_type.in_([resource_type] if resource_type else sorted(allowed)),
        PortalResource.visibility == "public",
        PortalResource.status == "published",
        PortalResource.organization_id.is_(None),
    )
    return [_out(row) for row in query.order_by(PortalResource.created_at.desc()).limit(limit).all()]


@router.get("/{portal}/resources")
def list_private_resources(
    portal: str,
    organization_id: int | None = Query(default=None, gt=0),
    resource_type: str | None = Query(default=None, min_length=2, max_length=48),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    portal = _portal(portal)
    allowed = PORTAL_TYPES[portal]
    if resource_type and resource_type not in allowed:
        raise HTTPException(404, "Portal resource type not found")
    memberships = db.query(Membership).filter_by(user_id=user.id, is_active=True).all()
    org_ids = [m.organization_id for m in memberships]
    if organization_id is not None:
        if organization_id not in org_ids:
            raise HTTPException(404, "Organization resource not found")
        org_ids = [organization_id]
    query = db.query(PortalResource).filter(
        PortalResource.portal == portal,
        PortalResource.resource_type.in_([resource_type] if resource_type else sorted(allowed)),
        or_(
            PortalResource.owner_user_id == user.id,
            PortalResource.organization_id.in_(org_ids) if org_ids else False,
        ),
    )
    rows = query.order_by(PortalResource.updated_at.desc()).limit(limit).all()
    result = []
    for row in rows:
        if row.organization_id is not None:
            membership = next((m for m in memberships if m.organization_id == row.organization_id), None)
            if not _role_allowed(row, user, membership):
                continue
        result.append(_out(row))
    return result


@router.post("/{portal}/resources", status_code=201)
def create_private_resource(
    portal: str, payload: PortalResourceIn,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    portal = _portal(portal)
    if payload.resource_type not in PORTAL_TYPES[portal]:
        raise HTTPException(422, "This resource type is not supported by the selected portal")
    if payload.organization_id is not None:
        membership = _membership(db, user, payload.organization_id)
        require_permission(membership, "create")
    stored_data, encrypted_payload = _stored_payload(payload.resource_type, payload.data)
    row = PortalResource(
        portal=portal, resource_type=payload.resource_type, title=payload.title.strip(),
        summary=payload.summary.strip(), data=stored_data, encrypted_payload=encrypted_payload,
        organization_id=payload.organization_id, owner_user_id=user.id,
        visibility="private", status="submitted" if portal in {"trust", "careers"} else "active",
    )
    db.add(row)
    db.flush()
    _audit(db, user, row, f"portal.{portal}.{payload.resource_type}.created")
    db.commit()
    db.refresh(row)
    return _out(row)


@router.get("/{portal}/resources/{resource_id}")
def read_private_resource(
    portal: str, resource_id: int,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    portal = _portal(portal)
    row = db.query(PortalResource).filter_by(id=resource_id, portal=portal).first()
    if not row:
        raise HTTPException(404, "Portal resource not found")
    _visible_resource(db, user, row)
    return _out(row)


@router.patch("/{portal}/resources/{resource_id}")
def update_private_resource(
    portal: str, resource_id: int, payload: PortalResourceUpdate,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    portal = _portal(portal)
    row = db.query(PortalResource).filter_by(id=resource_id, portal=portal).first()
    if not row:
        raise HTTPException(404, "Portal resource not found")
    membership = _visible_resource(db, user, row)
    if row.owner_user_id != user.id:
        if not membership:
            raise HTTPException(404, "Portal resource not found")
        require_permission(membership, "update")
    if row.status in {"closed", "resolved", "withdrawn", "rejected"}:
        raise HTTPException(409, "This portal record is closed and cannot be changed")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("data") is not None:
        row.data, row.encrypted_payload = _stored_payload(row.resource_type, changes.pop("data"))
    for key, value in changes.items():
        if value is not None:
            setattr(row, key, value)
    row.updated_at = datetime.now(timezone.utc)
    _audit(db, user, row, f"portal.{portal}.{row.resource_type}.updated")
    db.commit()
    db.refresh(row)
    return _out(row)


@router.delete("/{portal}/resources/{resource_id}", status_code=204)
def delete_private_resource(
    portal: str, resource_id: int,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    portal = _portal(portal)
    row = db.query(PortalResource).filter_by(id=resource_id, portal=portal).first()
    if not row:
        raise HTTPException(404, "Portal resource not found")
    membership = _visible_resource(db, user, row)
    if row.owner_user_id != user.id:
        if not membership:
            raise HTTPException(404, "Portal resource not found")
        require_permission(membership, "delete")
    _audit(db, user, row, f"portal.{portal}.{row.resource_type}.deleted")
    db.delete(row)
    db.commit()
    return None


@router.post("/{portal}/public/{resource_id}/publish")
def publish_public_resource(
    portal: str, resource_id: int,
    user: User = Depends(require_platform_admin), db: Session = Depends(get_db),
):
    portal = _portal(portal)
    row = db.query(PortalResource).filter_by(id=resource_id, portal=portal).first()
    if not row or row.resource_type not in PUBLIC_TYPES[portal] or row.organization_id is not None:
        raise HTTPException(404, "Publishable public resource not found")
    row.visibility = "public"
    row.status = "published"
    row.updated_at = datetime.now(timezone.utc)
    _audit(db, user, row, f"portal.{portal}.{row.resource_type}.published")
    db.commit()
    db.refresh(row)
    return _out(row)


@router.post("/{portal}/resources/{resource_id}/withdraw")
def withdraw_resource(
    portal: str, resource_id: int,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    portal = _portal(portal)
    row = db.query(PortalResource).filter_by(id=resource_id, portal=portal).first()
    if not row:
        raise HTTPException(404, "Portal resource not found")
    _visible_resource(db, user, row)
    if row.owner_user_id != user.id and user.platform_role not in {"root_superadmin", "platform_admin"}:
        raise HTTPException(404, "Portal resource not found")
    row.status = "withdrawn"
    row.updated_at = datetime.now(timezone.utc)
    _audit(db, user, row, f"portal.{portal}.{row.resource_type}.withdrawn")
    db.commit()
    return _out(row)
