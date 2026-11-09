from datetime import datetime, timedelta, timezone
import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import event, text
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.models import User, UserMFAFactor
from app.core.identity_models import UserSession

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# Platform administrators can reach customer data, tenant configuration and
# operational controls. Require a second factor before granting ordinary API
# sessions to these roles; enrollment tokens are restricted to MFA setup routes.
MFA_REQUIRED_PLATFORM_ROLES = frozenset({
    "root_superadmin",
    "platform_admin",
    "security_admin",
    "cms_admin",
    "support_admin",
    "developer_api_admin",
    "maintenance_admin",
    "incident_commander",
    "release_manager",
    "analytics_admin",
    "recruitment_admin",
})


def platform_role_requires_mfa(platform_role: str) -> bool:
    return str(platform_role or "").strip().lower() in MFA_REQUIRED_PLATFORM_ROLES

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)

def create_access_token(
    user_id: int,
    auth_version: int = 0,
    *,
    mfa_verified: bool = False,
    mfa_setup_only: bool = False,
    session_id: str | None = None,
    expires_at: datetime | None = None,
) -> str:
    lifetime_minutes = min(settings.access_token_expire_minutes, 10) if mfa_setup_only else settings.access_token_expire_minutes
    exp = expires_at or (datetime.now(timezone.utc) + timedelta(minutes=lifetime_minutes))
    claims = {"sub": str(user_id), "exp": exp, "ver": int(auth_version)}
    if mfa_verified:
        claims["mfa_verified"] = True
    if mfa_setup_only:
        claims["mfa_setup_only"] = True
    if session_id:
        claims["sid"] = str(session_id)
    return jwt.encode(claims, settings.secret_key, algorithm="HS256")

@event.listens_for(Session, "after_begin")
def _apply_database_identity_context(session, transaction, connection):
    """Set transaction-local identity for PostgreSQL RLS policies."""
    user_id = session.info.get("onecore_user_id")
    organization_id = session.info.get("onecore_organization_id")
    if connection.dialect.name == "postgresql":
        if user_id is not None:
            connection.execute(
                text("SELECT set_config('app.user_id', :user_id, true)"),
                {"user_id": str(user_id)},
            )
        if organization_id is not None:
            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(organization_id)},
            )


def set_verified_user_context(db: Session, user_id: int) -> None:
    """Bind a server-verified user identity to the current database transaction."""
    value = int(user_id)
    if value <= 0:
        raise ValueError("A positive user ID is required")
    db.info["onecore_user_id"] = value
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT set_config('app.user_id', :user_id, true)"),
            {"user_id": str(value)},
        )


def set_status_alert_fanout_context(db: Session, incident_record_id: int) -> None:
    """Authorize a platform-admin incident transaction to enqueue subscriber rows."""
    value = int(incident_record_id)
    if value <= 0:
        raise ValueError("A positive incident record ID is required")
    db.info["onecore_status_alert_incident_id"] = value
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT set_config('app.status_alert_incident_id', :incident_id, true)"),
            {"incident_id": str(value)},
        )


def set_verified_organization_context(db: Session, organization_id: int) -> None:
    """Scope trusted integration/worker transactions to a previously verified tenant."""
    value = int(organization_id)
    if value <= 0:
        raise ValueError("A positive organization ID is required")
    db.info["onecore_organization_id"] = value
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(value)},
        )


def set_provider_callback_token_context(db: Session, token_hash: str) -> None:
    """Allow one callback-token-bound row lookup before its tenant is known."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT set_config('app.provider_callback_token_hash', :token_hash, true)"),
            {"token_hash": token_hash},
        )


def set_crm_delivery_callback_context(db: Session, provider_message_id: str) -> None:
    """Authorize one provider-message lookup after the callback secret is verified."""
    value = str(provider_message_id).strip()
    if not value or len(value) > 255:
        raise ValueError("A valid provider message ID is required")
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT set_config('app.crm_delivery_provider_message_id', :message_id, true)"),
            {"message_id": value},
        )


def set_crm_unsubscribe_token_context(db: Session, token_hash: str) -> None:
    """Allow a public unsubscribe link to resolve only its token-bound delivery row."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT set_config('app.crm_unsubscribe_token_hash', :token_hash, true)"),
            {"token_hash": token_hash},
        )


def _resolve_current_user(token: str, db: Session, *, allow_mfa_setup_only: bool) -> User:
    error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = int(payload.get("sub", "0"))
        token_version = int(payload.get("ver", 0))
    except (jwt.InvalidTokenError, ValueError):
        raise error

    setup_only = payload.get("mfa_setup_only") is True
    if setup_only and not allow_mfa_setup_only:
        raise error

    # Bind the signed subject before reading account-owned RLS tables.
    try:
        set_verified_user_context(db, user_id)
    except ValueError:
        raise error
    user = db.get(User, user_id)
    if not user or not user.is_active or int(user.auth_version) != token_version:
        raise error

    session_id = payload.get("sid")
    db.info["onecore_session_id"] = None
    db.info["onecore_mfa_setup_only"] = setup_only
    db.info["onecore_mfa_verified"] = payload.get("mfa_verified") is True
    if session_id is not None:
        if not isinstance(session_id, str) or len(session_id) != 36:
            raise error
        session = db.query(UserSession).filter_by(id=session_id, user_id=user.id).first()
        if not session or session.revoked_at is not None:
            raise error
        session_expiry = session.expires_at
        if session_expiry.tzinfo is None:
            session_expiry = session_expiry.replace(tzinfo=timezone.utc)
        if session_expiry <= datetime.now(timezone.utc) or int(session.auth_version) != token_version:
            raise error
        db.info["onecore_session_id"] = session.id
        last_seen = session.last_seen_at
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if last_seen <= datetime.now(timezone.utc) - timedelta(minutes=5):
            session.last_seen_at = datetime.now(timezone.utc)
            # Authentication runs before endpoint code. Persist only the bounded
            # activity timestamp, then the transaction-start hook reapplies RLS.
            db.commit()

    if setup_only:
        # A setup token is deliberately accepted only by the three MFA setup
        # endpoints that depend on current_user_for_mfa_setup. It cannot be used
        # as a normal OneCore API bearer token or by a non-privileged account.
        if not platform_role_requires_mfa(user.platform_role):
            raise error
        factor = db.query(UserMFAFactor).filter(
            UserMFAFactor.user_id == user.id,
            UserMFAFactor.enabled_at.isnot(None),
        ).first()
        if factor:
            raise error
        return user

    if platform_role_requires_mfa(user.platform_role) and payload.get("mfa_verified") is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A verified second factor is required for privileged platform access.",
        )
    return user


def current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    return _resolve_current_user(token, db, allow_mfa_setup_only=False)


def current_user_for_mfa_setup(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Accept a normal user token or the restricted token used only to enroll MFA."""
    return _resolve_current_user(token, db, allow_mfa_setup_only=True)

def require_platform_admin(user: User = Depends(current_user)) -> User:
    if user.platform_role not in {"root_superadmin", "platform_admin"}:
        raise HTTPException(403, "Platform administrator role required")
    return user
