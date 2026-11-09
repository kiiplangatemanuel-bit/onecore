"""Helpers for issuing durable, revocable OneCore account sessions."""
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.identity_models import UserSession
from app.core.models import AuditEvent, User
from app.core.security import set_verified_user_context


ALLOWED_AUTH_METHODS = frozenset({"password", "totp", "recovery_code", "supabase", "portal"})


def create_user_session(
    db: Session,
    user: User,
    request=None,
    *,
    auth_method: str,
    mfa_verified: bool = False,
) -> UserSession:
    """Persist a user-owned session before its signed token is returned.

    Only the verified user identity is used for the session RLS context. Raw
    IP addresses and bearer tokens are deliberately not stored.
    """
    method = str(auth_method or "").strip().lower()
    if method not in ALLOWED_AUTH_METHODS:
        raise ValueError("Unsupported authentication method")
    set_verified_user_context(db, user.id)
    now = datetime.now(timezone.utc)
    lifetime = max(1, int(settings.access_token_expire_minutes))
    headers = getattr(request, "headers", {}) if request is not None else {}
    device_name = " ".join(str(headers.get("x-onecore-device-name", "")).split())[:120]
    user_agent = " ".join(str(headers.get("user-agent", "")).split())[:512]
    row = UserSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        auth_version=int(user.auth_version or 0),
        auth_method=method,
        mfa_verified=bool(mfa_verified),
        device_name=device_name,
        user_agent=user_agent,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(minutes=lifetime),
    )
    db.add(row)
    db.add(AuditEvent(
        actor_user_id=user.id,
        organization_id=None,
        action="auth.session.created",
        resource_type="user_session",
        resource_id=row.id,
        detail=f"method={method};mfa_verified={str(bool(mfa_verified)).lower()}",
    ))
    db.flush()
    return row
