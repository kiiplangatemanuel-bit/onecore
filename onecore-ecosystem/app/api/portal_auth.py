"""Secure, single-use PKCE handoff between independently deployed OneCore portals."""
import base64
import hashlib
import secrets
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.models import AuditEvent, PortalAuthorizationCode, User
from app.core.security import current_user, create_access_token

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class PortalCodeRequest(BaseModel):
    redirect_uri: str = Field(min_length=12, max_length=2048)
    state: str = Field(min_length=16, max_length=256)
    code_challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class PortalCodeExchange(BaseModel):
    code: str = Field(min_length=32, max_length=256)
    redirect_uri: str = Field(min_length=12, max_length=2048)
    code_verifier: str = Field(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9._~-]+$")


def _trusted_redirect(uri: str) -> str:
    parsed = urlsplit(uri)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise HTTPException(400, "Invalid portal redirect URI")
    if parsed.username or parsed.password or parsed.fragment:
        raise HTTPException(400, "Portal redirect URI cannot contain credentials or fragments")
    if parsed.scheme != "https" and not (
        settings.app_env.strip().lower() in {"development", "dev", "test"}
        and parsed.hostname in {"localhost", "127.0.0.1"}
    ):
        raise HTTPException(400, "Portal redirect URI must use HTTPS")
    origin = f"{parsed.scheme}://{parsed.netloc}".lower()
    configured = settings.portal_redirect_origins or settings.cors_origins
    allowed = {item.strip().rstrip("/").lower() for item in configured.split(",") if item.strip()}
    if origin not in allowed:
        raise HTTPException(400, "This portal origin is not registered for OneCore sign-in")
    return uri


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@router.post("/portal-code")
def issue_portal_code(
    payload: PortalCodeRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    redirect_uri = _trusted_redirect(payload.redirect_uri)
    raw_code = secrets.token_urlsafe(36)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=90)
    db.add(PortalAuthorizationCode(
        code_hash=_sha256(raw_code),
        user_id=user.id,
        redirect_uri=redirect_uri,
        code_challenge=payload.code_challenge,
        expires_at=expires_at,
    ))
    db.add(AuditEvent(
        actor_user_id=user.id,
        action="auth.portal_code.issued",
        resource_type="portal_auth",
        resource_id=secrets.token_hex(8),
        detail=urlsplit(redirect_uri).netloc,
    ))
    db.commit()
    parsed = urlsplit(redirect_uri)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend([("code", raw_code), ("state", payload.state)])
    destination = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
    return {"redirect_url": destination, "expires_in": 90, "token_type": "code"}


@router.post("/exchange-portal-code")
def exchange_portal_code(payload: PortalCodeExchange, db: Session = Depends(get_db)):
    redirect_uri = _trusted_redirect(payload.redirect_uri)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(payload.code_verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge):
        raise HTTPException(400, "Invalid PKCE verifier")
    row = db.query(PortalAuthorizationCode).filter_by(
        code_hash=_sha256(payload.code)
    ).with_for_update().first()
    now = datetime.now(timezone.utc)
    if not row or row.consumed_at is not None:
        raise HTTPException(400, "Portal authorization code is invalid or already used")
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise HTTPException(400, "Portal authorization code has expired")
    if row.redirect_uri != redirect_uri or not secrets.compare_digest(row.code_challenge, challenge):
        raise HTTPException(400, "Portal authorization code validation failed")
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "The OneCore account is no longer active")
    row.consumed_at = now
    db.add(AuditEvent(
        actor_user_id=user.id,
        action="auth.portal_code.exchanged",
        resource_type="portal_auth",
        resource_id=str(row.id),
        detail=urlsplit(redirect_uri).netloc,
    ))
    db.commit()
    return {"access_token": create_access_token(user.id, user.auth_version), "token_type": "bearer"}
