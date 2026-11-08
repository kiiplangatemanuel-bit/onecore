from datetime import datetime, timedelta, timezone
import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import event, text
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.models import User

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)

def create_access_token(user_id: int, auth_version: int = 0) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({"sub": str(user_id), "exp": exp, "ver": int(auth_version)}, settings.secret_key, algorithm="HS256")

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


def set_crm_delivery_callback_context(db: Session) -> None:
    """Authorize the CRM delivery callback only after its shared secret is verified."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT set_config('app.crm_delivery_callback_authenticated', 'true', true)"))


def set_crm_unsubscribe_token_context(db: Session, token_hash: str) -> None:
    """Allow a public unsubscribe link to resolve only its token-bound delivery row."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT set_config('app.crm_unsubscribe_token_hash', :token_hash, true)"),
            {"token_hash": token_hash},
        )


def current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired credentials",
                          headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = int(payload.get("sub", "0"))
        token_version = int(payload.get("ver", 0))
    except (jwt.InvalidTokenError, ValueError):
        raise error
    # SQLAlchemy applies this identity on every new PostgreSQL transaction, including
    # after an endpoint commits and starts another transaction in the same request.
    db.info["onecore_user_id"] = user_id
    user = db.get(User, user_id)
    if not user or not user.is_active or int(user.auth_version) != token_version:
        raise error
    return user

def require_platform_admin(user: User = Depends(current_user)) -> User:
    if user.platform_role not in {"root_superadmin", "platform_admin"}:
        raise HTTPException(403, "Platform administrator role required")
    return user
