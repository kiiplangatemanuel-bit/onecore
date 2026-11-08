"""Real organization-scoped developer API key lifecycle and authenticated API example."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import (
    AuditEvent, DeveloperApiKey, DeveloperApiKeyUsage, Membership, Organization, User,
)
from app.core.security import current_user

router = APIRouter(prefix="/api/v1/developer", tags=["developer API credentials"])

ALLOWED_SCOPES = {"organization:read"}


class DeveloperApiKeyCreate(BaseModel):
    organization_id: int = Field(gt=0)
    name: str = Field(min_length=2, max_length=120)
    environment: str = Field(default="sandbox", pattern=r"^(sandbox|production)$")
    scopes: list[str] = Field(default_factory=lambda: ["organization:read"], min_length=1, max_length=5)
    expires_in_days: int = Field(default=90, ge=1, le=365)


def _now():
    return datetime.now(timezone.utc)


def _key_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _membership(db: Session, user: User, organization_id: int) -> Membership:
    membership = db.query(Membership).filter_by(
        user_id=user.id, organization_id=organization_id, is_active=True
    ).first()
    if not membership or membership.role not in {"org_admin", "developer"}:
        raise HTTPException(404, "Developer resource not found")
    return membership


def _can_manage_key(db: Session, key: DeveloperApiKey, user: User) -> bool:
    membership = db.query(Membership).filter_by(
        user_id=user.id, organization_id=key.organization_id, is_active=True
    ).first()
    if not membership or membership.role not in {"org_admin", "developer"}:
        return False
    return membership.role == "org_admin" or key.created_by_user_id == user.id


def _key_out(key: DeveloperApiKey, usage_count: int = 0) -> dict:
    return {
        "id": key.id, "organization_id": key.organization_id, "name": key.name,
        "key_prefix": key.key_prefix, "environment": key.environment,
        "scopes": key.scopes, "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
        "created_at": key.created_at.isoformat(), "usage_count": usage_count,
    }


@router.post("/api-keys", status_code=201)
def create_developer_api_key(
    payload: DeveloperApiKeyCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    _membership(db, user, payload.organization_id)
    invalid = sorted(set(payload.scopes) - ALLOWED_SCOPES)
    if invalid:
        raise HTTPException(422, {"message": "Unsupported API key scopes", "scopes": invalid})
    organization = db.query(Organization).filter_by(
        id=payload.organization_id, is_active=True
    ).first()
    if not organization:
        raise HTTPException(404, "Developer resource not found")
    raw_key = f"oc_{'live' if payload.environment == 'production' else 'test'}_{secrets.token_urlsafe(36)}"
    key = DeveloperApiKey(
        organization_id=organization.id, created_by_user_id=user.id,
        name=payload.name.strip(), key_prefix=raw_key[:16],
        secret_hash=_key_hash(raw_key), scopes=sorted(set(payload.scopes)),
        environment=payload.environment,
        expires_at=_now() + timedelta(days=payload.expires_in_days),
    )
    db.add(key)
    db.flush()
    db.add(AuditEvent(
        actor_user_id=user.id, organization_id=organization.id,
        action="developer.api_key.created", resource_type="developer_api_key",
        resource_id=str(key.id), detail=f"prefix={key.key_prefix};environment={key.environment}",
    ))
    db.commit()
    db.refresh(key)
    # Plaintext is deliberately returned exactly once and never persisted.
    return {**_key_out(key), "secret": raw_key}


@router.get("/api-keys")
def list_developer_api_keys(
    organization_id: int = Query(gt=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    membership = _membership(db, user, organization_id)
    query = db.query(DeveloperApiKey).filter_by(organization_id=organization_id)
    if membership.role != "org_admin":
        query = query.filter_by(created_by_user_id=user.id)
    rows = query.order_by(DeveloperApiKey.created_at.desc()).all()
    counts = dict(db.query(
        DeveloperApiKeyUsage.api_key_id, func.count(DeveloperApiKeyUsage.id)
    ).filter(DeveloperApiKeyUsage.api_key_id.in_([row.id for row in rows])).group_by(
        DeveloperApiKeyUsage.api_key_id
    ).all()) if rows else {}
    return [_key_out(row, counts.get(row.id, 0)) for row in rows]


@router.post("/api-keys/{key_id}/revoke")
def revoke_developer_api_key(
    key_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    key = db.query(DeveloperApiKey).filter_by(id=key_id).with_for_update().first()
    if not key or not _can_manage_key(db, key, user):
        raise HTTPException(404, "Developer API key not found")
    if key.revoked_at is None:
        key.revoked_at = _now()
        db.add(AuditEvent(
            actor_user_id=user.id, organization_id=key.organization_id,
            action="developer.api_key.revoked", resource_type="developer_api_key",
            resource_id=str(key.id), detail=f"prefix={key.key_prefix}",
        ))
        db.commit()
    return {"id": key.id, "revoked": True, "revoked_at": key.revoked_at.isoformat()}


@router.get("/api-keys/{key_id}/usage")
def get_developer_api_key_usage(
    key_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    key = db.query(DeveloperApiKey).filter_by(id=key_id).first()
    if not key or not _can_manage_key(db, key, user):
        raise HTTPException(404, "Developer API key not found")
    rows = db.query(DeveloperApiKeyUsage).filter_by(api_key_id=key.id).order_by(
        DeveloperApiKeyUsage.occurred_at.desc()
    ).limit(limit).all()
    total = db.query(func.count(DeveloperApiKeyUsage.id)).filter_by(api_key_id=key.id).scalar() or 0
    return {
        "api_key_id": key.id, "total_requests": total,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "items": [{
            "endpoint": row.endpoint, "method": row.method,
            "status_code": row.status_code, "occurred_at": row.occurred_at.isoformat(),
        } for row in rows],
    }


def current_developer_api_key(
    request: Request,
    x_onecore_api_key: str = Header(default="", alias="X-OneCore-API-Key"),
    db: Session = Depends(get_db),
) -> DeveloperApiKey:
    """Authenticate a dedicated developer credential and bind its identity to RLS."""
    if not x_onecore_api_key or len(x_onecore_api_key) < 40 or len(x_onecore_api_key) > 256:
        raise HTTPException(401, "A valid X-OneCore-API-Key header is required")
    digest = _key_hash(x_onecore_api_key)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT set_config('app.developer_api_key_hash', :digest, true)"),
                   {"digest": digest})
    key = db.query(DeveloperApiKey).filter_by(secret_hash=digest).first()
    now = _now()
    if not key or key.revoked_at is not None:
        raise HTTPException(401, "Developer API key is invalid or revoked")
    expires_at = key.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise HTTPException(401, "Developer API key has expired")
    organization = db.query(Organization).filter_by(id=key.organization_id, is_active=True).first()
    membership = db.query(Membership).filter_by(
        user_id=key.created_by_user_id, organization_id=key.organization_id, is_active=True
    ).first()
    if not organization or not membership or membership.role not in {"org_admin", "developer"}:
        raise HTTPException(401, "Developer API key owner no longer has active organization access")
    db.info["onecore_user_id"] = key.created_by_user_id
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT set_config('app.user_id', :user_id, true)"),
                   {"user_id": str(key.created_by_user_id)})
    request.state.developer_api_key_id = key.id
    return key


@router.get("/v1/organization")
def developer_api_organization(
    request: Request,
    key: DeveloperApiKey = Depends(current_developer_api_key),
    db: Session = Depends(get_db),
):
    if "organization:read" not in (key.scopes or []):
        raise HTTPException(403, "API key does not grant organization:read")
    organization = db.query(Organization).filter_by(id=key.organization_id, is_active=True).first()
    if not organization:
        raise HTTPException(404, "Organization not found")
    db.add(DeveloperApiKeyUsage(
        api_key_id=key.id, organization_id=key.organization_id,
        endpoint=request.url.path[:255], method=request.method,
        status_code=200,
    ))
    key.last_used_at = _now()
    db.commit()
    return {
        "organization": {
            "id": organization.id, "name": organization.name,
            "slug": organization.slug, "industry": organization.industry,
            "country": organization.country, "currency": organization.currency,
        },
        "api_key": {"prefix": key.key_prefix, "environment": key.environment},
    }
