"""Authenticated account session inventory and per-device revocation."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.identity_models import UserSession
from app.core.models import AuditEvent, User
from app.core.security import current_user


router = APIRouter(prefix="/api/v1/auth/sessions", tags=["authentication"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _session_view(row: UserSession, current_session_id: str | None) -> dict:
    return {
        "id": row.id,
        "device_name": row.device_name,
        "user_agent": row.user_agent,
        "auth_method": row.auth_method,
        "mfa_verified": bool(row.mfa_verified),
        "created_at": _utc(row.created_at).isoformat(),
        "last_seen_at": _utc(row.last_seen_at).isoformat(),
        "expires_at": _utc(row.expires_at).isoformat(),
        "revoked_at": _utc(row.revoked_at).isoformat() if row.revoked_at else None,
        "revoked_reason": row.revoked_reason,
        "current": row.id == current_session_id,
    }


@router.get("")
def list_user_sessions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    current_session_id = db.info.get("onecore_session_id")
    rows = db.query(UserSession).filter_by(user_id=user.id).order_by(
        UserSession.created_at.desc()
    ).limit(50).all()
    return {
        "sessions": [_session_view(row, current_session_id) for row in rows],
        "current_session_id": current_session_id,
        "legacy_session": current_session_id is None,
    }


@router.post("/revoke-others")
def revoke_other_sessions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    current_session_id = db.info.get("onecore_session_id")
    if not current_session_id:
        raise HTTPException(
            409,
            "This sign-in predates device tracking. Sign in again before revoking other sessions.",
        )
    now = _now()
    rows = db.query(UserSession).filter(
        UserSession.user_id == user.id,
        UserSession.id != current_session_id,
        UserSession.revoked_at.is_(None),
        UserSession.expires_at > now,
    ).with_for_update().all()
    for row in rows:
        row.revoked_at = now
        row.revoked_reason = "user_revoked_other_sessions"
    db.add(AuditEvent(
        actor_user_id=user.id,
        organization_id=None,
        action="auth.sessions.other_sessions_revoked",
        resource_type="user",
        resource_id=str(user.id),
        detail=f"revoked_count={len(rows)}",
    ))
    db.commit()
    return {"status": "revoked", "revoked_count": len(rows), "current_session_id": current_session_id}


@router.delete("/{session_id}")
def revoke_user_session(
    session_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = db.query(UserSession).filter_by(id=session_id, user_id=user.id).with_for_update().first()
    if not row:
        raise HTTPException(404, "Session not found")
    current_session_id = db.info.get("onecore_session_id")
    if row.revoked_at is None:
        row.revoked_at = _now()
        row.revoked_reason = "user_revoked_session"
        db.add(AuditEvent(
            actor_user_id=user.id,
            organization_id=None,
            action="auth.session.revoked",
            resource_type="user_session",
            resource_id=row.id,
            detail="user_requested",
        ))
        db.commit()
    return {"status": "revoked", "current_session": row.id == current_session_id}
