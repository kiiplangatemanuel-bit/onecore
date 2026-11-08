"""Tenant-safe authenticated workflows for OneCore's public application suite.

This API intentionally keeps public discovery separate from authenticated write APIs.
Every organization record is selected through an active membership; confidential trust
and applicant records are always private to their owner.
"""
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import AuditEvent, Membership, PortalWorkflowRecord, User
from app.core.security import current_user

router = APIRouter(prefix="/api/v1/portals", tags=["public portals"])

PORTALS = {"status", "developers", "docs", "community", "trust", "events", "careers", "partners"}
PUBLIC_TYPES = {
    "status": {"incident"},
    "developers": {"api_guide", "example"},
    "docs": {"guide"},
    "community": {"announcement", "public_post"},
    "trust": {"security_policy", "compliance_disclosure"},
    "events": {"event", "announcement"},
    "careers": {"vacancy", "company_information"},
    "partners": {"opportunity", "partner_information"},
}
PERSONAL_TYPES = {
    ("status", "alert_subscription"), ("status", "notification_preference"),
    ("trust", "security_report"), ("careers", "applicant_profile"), ("careers", "application"),
    ("events", "registration"), ("events", "booking"), ("community", "profile"),
}
ALLOWED_TYPES = {
    "status": {"alert_subscription", "notification_preference", "incident"},
    "developers": {"application", "api_key", "webhook", "sandbox_environment"},
    "docs": {"organization_guide"},
    "community": {"post", "comment", "group", "profile"},
    "trust": {"security_report"},
    "events": {"registration", "booking", "attendance"},
    "careers": {"applicant_profile", "application"},
    "partners": {"partner_profile", "referral", "lead", "agreement", "partner_resource"},
}
REQUIRED_FIELDS = {
    ("status", "alert_subscription"): {"service"},
    ("status", "notification_preference"): {"channel"},
    ("developers", "application"): {"name"},
    ("developers", "api_key"): {"name", "scopes"},
    ("developers", "webhook"): {"name", "endpoint_url", "events"},
    ("developers", "sandbox_environment"): {"name"},
    ("docs", "organization_guide"): {"title", "body"},
    ("community", "post"): {"title", "body"},
    ("community", "comment"): {"post_id", "body"},
    ("community", "group"): {"name"},
    ("community", "profile"): {"display_name"},
    ("trust", "security_report"): {"title", "description", "severity"},
    ("events", "registration"): {"event_id"},
    ("events", "booking"): {"event_id"},
    ("events", "attendance"): {"event_id", "attendee_user_id"},
    ("careers", "applicant_profile"): {"full_name", "email"},
    ("careers", "application"): {"vacancy_id", "cover_letter"},
    ("partners", "partner_profile"): {"organization_name"},
    ("partners", "referral"): {"company_name", "contact_email"},
    ("partners", "lead"): {"company_name", "contact_email"},
    ("partners", "agreement"): {"title"},
    ("partners", "partner_resource"): {"title", "body"},
}
WRITE_ROLES = {
    "developers": {"org_admin", "developer", "manager"},
    "docs": {"org_admin", "manager", "school_admin", "teacher"},
    "community": {"org_admin", "branch_admin", "manager", "staff", "teacher"},
    "events": {"org_admin", "event_manager", "manager"},
    "partners": {"org_admin", "partner_manager", "manager"},
}
MANAGER_ONLY = {
    ("developers", "application"), ("developers", "api_key"), ("developers", "webhook"),
    ("developers", "sandbox_environment"), ("docs", "organization_guide"),
    ("community", "group"), ("events", "attendance"),
    ("partners", "partner_profile"), ("partners", "agreement"), ("partners", "partner_resource"),
}
STATUS_TRANSITIONS = {
    ("trust", "security_report"): {"submitted", "acknowledged", "investigating", "resolved", "closed"},
    ("careers", "application"): {"submitted", "screening", "interview", "offer", "rejected", "withdrawn"},
    ("events", "registration"): {"registered", "waitlisted", "cancelled", "attended"},
    ("events", "booking"): {"booked", "cancelled", "attended"},
    ("partners", "lead"): {"new", "qualified", "contacted", "converted", "rejected"},
    ("partners", "referral"): {"submitted", "accepted", "rejected", "converted"},
    ("developers", "api_key"): {"active", "revoked"},
    ("developers", "webhook"): {"active", "disabled"},
}


class PortalRecordCreate(BaseModel):
    organization_id: int | None = Field(default=None, gt=0)
    payload: dict[str, Any] = Field(min_length=1, max_length=80)
    visibility: str = Field(default="private", pattern=r"^(private|organization)$")


class PortalRecordUpdate(BaseModel):
    payload: dict[str, Any] | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, min_length=2, max_length=24)


class PortalPublicContentCreate(BaseModel):
    payload: dict[str, Any] = Field(min_length=1, max_length=80)


def _membership(db: Session, user: User, organization_id: int) -> Membership:
    membership = db.query(Membership).filter_by(
        user_id=user.id, organization_id=organization_id, is_active=True
    ).first()
    if not membership:
        raise HTTPException(404, "Portal record not found")
    return membership


def _can_read(row: PortalWorkflowRecord, user: User, db: Session) -> bool:
    if row.owner_user_id == user.id:
        return True
    if row.visibility != "organization":
        return False
    if (row.portal_key, row.record_type) in PERSONAL_TYPES or row.portal_key == "trust" or row.portal_key == "careers":
        return False
    if row.organization_id is None:
        return False
    return db.query(Membership.id).filter_by(
        user_id=user.id, organization_id=row.organization_id, is_active=True
    ).first() is not None


def _can_manage(row: PortalWorkflowRecord, user: User, db: Session) -> bool:
    if row.owner_user_id == user.id:
        return True
    if row.organization_id is None or row.portal_key in {"trust", "careers"}:
        return False
    membership = db.query(Membership).filter_by(
        user_id=user.id, organization_id=row.organization_id, is_active=True
    ).first()
    if not membership:
        return False
    if (row.portal_key, row.record_type) in MANAGER_ONLY:
        return membership.role in {"org_admin", "manager", "school_admin", "partner_manager", "developer", "event_manager"}
    return membership.role in {"org_admin", "manager"}


def _out(row: PortalWorkflowRecord) -> dict:
    return {
        "id": row.id, "portal": row.portal_key, "record_type": row.record_type,
        "organization_id": row.organization_id, "owner_user_id": row.owner_user_id,
        "visibility": row.visibility, "status": row.status, "payload": row.payload,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
    }


def _audit(db: Session, user: User, row: PortalWorkflowRecord, action: str):
    db.add(AuditEvent(
        organization_id=row.organization_id, actor_user_id=user.id, action=action,
        resource_type="portal_workflow_record", resource_id=str(row.id),
        detail=f"{row.portal_key}:{row.record_type}:{row.status}",
    ))


def _validate_payload(portal: str, record_type: str, payload: dict):
    required = REQUIRED_FIELDS.get((portal, record_type), set())
    required = required | {
        ("status", "incident"): {"title", "service", "severity", "summary"},
        ("developers", "api_guide"): {"title", "body"},
        ("developers", "example"): {"title", "language", "code"},
        ("docs", "guide"): {"title", "slug", "body"},
        ("community", "announcement"): {"title", "body"},
        ("community", "public_post"): {"title", "body"},
        ("trust", "security_policy"): {"title", "body"},
        ("trust", "compliance_disclosure"): {"title", "body"},
        ("events", "event"): {"title", "starts_at", "description"},
        ("events", "announcement"): {"title", "body"},
        ("careers", "vacancy"): {"title", "description", "location"},
        ("careers", "company_information"): {"title", "body"},
        ("partners", "opportunity"): {"title", "description"},
        ("partners", "partner_information"): {"title", "body"},
    }.get((portal, record_type), set())
    missing = sorted(key for key in required if key not in payload or payload[key] in (None, "", []))
    if missing:
        raise HTTPException(422, {"message": "Required portal fields are missing", "fields": missing})
    if len(str(payload).encode("utf-8")) > 48_000:
        raise HTTPException(413, "Portal record payload exceeds 48 KB")
    if portal == "developers" and record_type == "webhook":
        endpoint = str(payload.get("endpoint_url", ""))
        if not endpoint.startswith("https://") or len(endpoint) > 2048:
            raise HTTPException(422, "Webhook endpoints must use HTTPS")
    if portal == "developers" and record_type == "api_key":
        scopes = payload.get("scopes")
        if not isinstance(scopes, list) or not scopes or len(scopes) > 50 or any(not isinstance(x, str) or len(x) > 80 for x in scopes):
            raise HTTPException(422, "API key scopes must be a non-empty list of at most 50 scope names")
        if "secret" in payload or "token" in payload or "api_key" in payload:
            raise HTTPException(422, "Credential secrets cannot be stored in portal record payloads")


@router.get("/{portal}/public/{record_type}")
def list_public_portal_content(
    portal: str, record_type: str, limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Unauthenticated, published-only public content. Never returns tenant records."""
    if portal not in PORTALS or record_type not in PUBLIC_TYPES.get(portal, set()):
        raise HTTPException(404, "Public portal resource not found")
    rows = db.query(PortalWorkflowRecord).filter_by(
        portal_key=portal, record_type=record_type, organization_id=None,
        visibility="public", status="published",
    ).order_by(PortalWorkflowRecord.updated_at.desc()).limit(limit).all()
    return [_out(row) for row in rows]


@router.get("/{portal}/records")
def list_portal_records(
    portal: str, record_type: str = Query(min_length=2, max_length=48),
    organization_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    if portal not in PORTALS or record_type not in ALLOWED_TYPES.get(portal, set()):
        raise HTTPException(404, "Portal resource not found")
    query = db.query(PortalWorkflowRecord).filter_by(portal_key=portal, record_type=record_type)
    if (portal, record_type) in PERSONAL_TYPES or portal in {"trust", "careers"}:
        query = query.filter_by(owner_user_id=user.id)
    else:
        memberships = db.query(Membership.organization_id).filter_by(
            user_id=user.id, is_active=True
        )
        org_ids = [item[0] for item in memberships.all()]
        if organization_id is not None:
            if organization_id not in org_ids:
                raise HTTPException(404, "Portal resource not found")
            org_ids = [organization_id]
        if not org_ids:
            return []
        query = query.filter(or_(
            PortalWorkflowRecord.owner_user_id == user.id,
            and_(PortalWorkflowRecord.organization_id.in_(org_ids), PortalWorkflowRecord.visibility == "organization"),
        ))
    rows = query.order_by(PortalWorkflowRecord.updated_at.desc()).limit(limit).all()
    return [_out(row) for row in rows]


@router.post("/{portal}/records/{record_type}", status_code=201)
def create_portal_record(
    portal: str, record_type: str, payload: PortalRecordCreate,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    if portal not in PORTALS or record_type not in ALLOWED_TYPES.get(portal, set()):
        raise HTTPException(404, "Portal resource not found")
    _validate_payload(portal, record_type, payload.payload)
    personal = (portal, record_type) in PERSONAL_TYPES or portal in {"trust", "careers"}
    if personal and payload.organization_id is not None:
        raise HTTPException(422, "This record is personal and cannot be attached to an organization")
    if personal and payload.visibility != "private":
        raise HTTPException(422, "Personal portal records must remain private")
    if not personal and payload.organization_id is None:
        raise HTTPException(422, "An organization is required for this portal workflow")
    if payload.organization_id is not None:
        membership = _membership(db, user, payload.organization_id)
        allowed_roles = WRITE_ROLES.get(portal, {"org_admin", "manager", "staff"})
        if (portal, record_type) in MANAGER_ONLY:
            allowed_roles = {"org_admin", "manager", "school_admin", "partner_manager", "developer", "event_manager"}
        if membership.role not in allowed_roles:
            raise HTTPException(403, "Your organization role cannot create this portal resource")
    initial_status = {
        ("trust", "security_report"): "submitted",
        ("careers", "application"): "submitted",
        ("events", "registration"): "registered",
        ("events", "booking"): "booked",
        ("status", "alert_subscription"): "active",
        ("status", "notification_preference"): "active",
        ("developers", "api_key"): "active",
        ("developers", "webhook"): "active",
    }.get((portal, record_type), "draft")
    row = PortalWorkflowRecord(
        portal_key=portal, record_type=record_type,
        organization_id=payload.organization_id, owner_user_id=user.id,
        visibility=payload.visibility, status=initial_status, payload=payload.payload,
    )
    db.add(row)
    db.flush()
    _audit(db, user, row, f"portal.{portal}.{record_type}.created")
    db.commit()
    db.refresh(row)
    return _out(row)


@router.get("/{portal}/records/{record_id}")
def read_portal_record(
    portal: str, record_id: int, user: User = Depends(current_user), db: Session = Depends(get_db),
):
    if portal not in PORTALS:
        raise HTTPException(404, "Portal record not found")
    row = db.query(PortalWorkflowRecord).filter_by(id=record_id, portal_key=portal).first()
    if not row or not _can_read(row, user, db):
        raise HTTPException(404, "Portal record not found")
    return _out(row)


@router.patch("/{portal}/records/{record_id}")
def update_portal_record(
    portal: str, record_id: int, payload: PortalRecordUpdate,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    if portal not in PORTALS:
        raise HTTPException(404, "Portal record not found")
    row = db.query(PortalWorkflowRecord).filter_by(id=record_id, portal_key=portal).with_for_update().first()
    if not row or not _can_manage(row, user, db):
        raise HTTPException(404, "Portal record not found")
    if payload.payload is not None:
        if (portal, row.record_type) in PERSONAL_TYPES or portal in {"trust", "careers"}:
            if row.owner_user_id != user.id:
                raise HTTPException(404, "Portal record not found")
        _validate_payload(portal, row.record_type, {**row.payload, **payload.payload})
        row.payload = {**row.payload, **payload.payload}
    if payload.status is not None:
        allowed = STATUS_TRANSITIONS.get((portal, row.record_type), set())
        if payload.status not in allowed:
            raise HTTPException(422, "Unsupported status transition")
        if row.owner_user_id != user.id and not _can_manage(row, user, db):
            raise HTTPException(403, "Insufficient portal permissions")
        if row.record_type in {"security_report", "application"} and row.owner_user_id == user.id:
            raise HTTPException(403, "Submitted records are reviewed by authorized staff; owners cannot change case status")
        row.status = payload.status
    row.updated_at = datetime.now(timezone.utc)
    _audit(db, user, row, f"portal.{portal}.{row.record_type}.updated")
    db.commit()
    db.refresh(row)
    return _out(row)


@router.post("/admin/{portal}/public/{record_type}", status_code=201)
def publish_public_portal_content(
    portal: str, record_type: str, payload: PortalPublicContentCreate,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    """Publish global public content; only platform administrators may publish."""
    if user.platform_role not in {"root_superadmin", "platform_admin"}:
        raise HTTPException(403, "Platform administrator access is required")
    if portal not in PORTALS or record_type not in PUBLIC_TYPES.get(portal, set()):
        raise HTTPException(404, "Public portal resource not found")
    _validate_payload(portal, record_type, payload.payload)
    row = PortalWorkflowRecord(
        portal_key=portal, record_type=record_type, organization_id=None,
        owner_user_id=user.id, visibility="public", status="published",
        payload=payload.payload,
    )
    db.add(row)
    db.flush()
    _audit(db, user, row, f"portal.{portal}.{record_type}.published")
    db.commit()
    db.refresh(row)
    return _out(row)
