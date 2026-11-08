from datetime import datetime, timedelta, timezone
import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.config import settings
from app.core.database import get_db
from app.core.models import User

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)

def create_access_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({"sub": str(user_id), "exp": exp}, settings.secret_key, algorithm="HS256")

def _supabase_user(token: str, db: Session) -> User:
    if not settings.supabase_url.strip():
        raise jwt.InvalidTokenError("Supabase Auth is not configured")
    issuer = settings.supabase_url.rstrip("/") + "/auth/v1"
    if settings.supabase_jwt_secret:
        payload = jwt.decode(
            token, settings.supabase_jwt_secret, algorithms=["HS256"],
            audience="authenticated", issuer=issuer,
        )
    else:
        # Supabase projects using asymmetric signing publish the verification key set.
        client = jwt.PyJWKClient(issuer + "/.well-known/jwks.json", cache_jwk_set=True)
        signing_key = client.get_signing_key_from_jwt(token).key
        payload = jwt.decode(
            token, signing_key, algorithms=["ES256", "RS256"],
            audience="authenticated", issuer=issuer,
        )
    subject = str(payload.get("sub") or "")
    email = str(payload.get("email") or "").strip().lower()
    if not subject or not email or payload.get("role") != "authenticated" or payload.get("email_verified") is not True:
        raise jwt.InvalidTokenError("Supabase identity must be authenticated and email verified")
    user = db.query(User).filter_by(supabase_auth_user_id=subject).first()
    if user is None:
        # Link only a verified Supabase identity to an existing OneCore account with
        # the exact same email; never auto-provision tenant access from an arbitrary JWT.
        user = db.query(User).filter(func.lower(User.email) == email).first()
        if user is None or not user.is_active:
            raise jwt.InvalidTokenError("No active OneCore account is linked to this Supabase identity")
        if user.supabase_auth_user_id and user.supabase_auth_user_id != subject:
            raise jwt.InvalidTokenError("Supabase identity is already linked to another account")
        user.supabase_auth_user_id = subject
        db.commit()
    if not user.is_active:
        raise jwt.InvalidTokenError("OneCore account is inactive")
    return user


def current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired credentials",
                          headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = int(payload.get("sub", "0"))
        user = db.get(User, user_id)
        if user and user.is_active:
            return user
    except (jwt.InvalidTokenError, ValueError, TypeError):
        pass
    try:
        return _supabase_user(token, db)
    except Exception:
        raise error

def require_platform_admin(user: User = Depends(current_user)) -> User:
    if user.platform_role not in {"root_superadmin", "platform_admin"}:
        raise HTTPException(403, "Platform administrator role required")
    return user
