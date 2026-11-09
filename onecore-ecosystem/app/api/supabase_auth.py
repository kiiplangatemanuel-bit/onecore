"""Supabase Auth token verification and OneCore session exchange.

The Supabase Auth service validates the supplied access token. OneCore then maps
that verified identity to a local user and issues its short-lived API session so
all independently deployed portals retain the existing PKCE handoff contract.
"""
import secrets
import uuid

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.models import AuditEvent, User, UserMFAFactor
from app.core.security import create_access_token, hash_password, platform_role_requires_mfa
from app.services.user_sessions import create_user_session

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class SupabaseSessionExchange(BaseModel):
    access_token: str = Field(min_length=20, max_length=4096)


def _verified_supabase_user(access_token: str) -> dict:
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(503, "Supabase Auth is not configured for this OneCore deployment")
    endpoint = settings.supabase_url.rstrip("/") + "/auth/v1/user"
    try:
        response = httpx.get(
            endpoint,
            headers={
                "apikey": settings.supabase_anon_key,
                "Authorization": f"Bearer {access_token}",
            },
            timeout=8.0,
        )
    except httpx.RequestError as exc:
        raise HTTPException(503, "Supabase Auth could not be reached") from exc
    if response.status_code in {401, 403}:
        raise HTTPException(401, "Supabase access token is invalid or expired")
    if response.status_code != 200:
        raise HTTPException(503, "Supabase Auth could not validate the session")
    try:
        identity = response.json()
    except ValueError as exc:
        raise HTTPException(503, "Supabase Auth returned an invalid identity response") from exc
    if not isinstance(identity, dict):
        raise HTTPException(503, "Supabase Auth returned an invalid identity response")
    try:
        identity["id"] = str(uuid.UUID(str(identity.get("id", ""))))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(401, "Supabase identity is invalid") from exc
    email = str(identity.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(401, "A verified email address is required for OneCore sign-in")
    if not (identity.get("email_confirmed_at") or identity.get("confirmed_at")):
        raise HTTPException(403, "Verify your email address with Supabase before signing in to OneCore")
    if identity.get("is_anonymous") is True:
        raise HTTPException(403, "Anonymous Supabase sessions cannot access authenticated OneCore features")
    identity["email"] = email
    return identity


@router.post("/supabase-session")
def exchange_supabase_session(
    payload: SupabaseSessionExchange,
    db: Session = Depends(get_db),
    request: Request = None,
):
    identity = _verified_supabase_user(payload.access_token)
    supabase_id = identity["id"]
    email = identity["email"]

    user = db.query(User).filter_by(supabase_auth_user_id=supabase_id).first()
    if user:
        if user.email.lower() != email:
            raise HTTPException(409, "The verified Supabase email differs from the linked OneCore account")
        if not user.is_active:
            raise HTTPException(403, "This OneCore account is disabled")
    else:
        user = db.query(User).filter(func.lower(User.email) == email).first()
        if user:
            if not user.is_active:
                raise HTTPException(403, "This OneCore account is disabled")
            if user.supabase_auth_user_id and user.supabase_auth_user_id != supabase_id:
                raise HTTPException(409, "This OneCore account is already linked to another Supabase identity")
            user.supabase_auth_user_id = supabase_id
            action = "auth.supabase.identity_linked"
        else:
            metadata = identity.get("user_metadata") or {}
            full_name = str(metadata.get("full_name") or metadata.get("name") or "").strip()[:180]
            user = User(
                email=email, full_name=full_name or email.split("@")[0],
                password_hash=hash_password(secrets.token_urlsafe(64)),
                is_active=True, platform_role="customer",
                supabase_auth_user_id=supabase_id,
            )
            db.add(user)
            action = "auth.supabase.user_provisioned"
    # A Supabase password session must not bypass a OneCore MFA factor.
    # Supabase validates the JWT at /auth/v1/user above; after that verification,
    # inspect its signed AAL claim and bind it to the verified subject.
    mfa_factor = db.query(UserMFAFactor).filter(
        UserMFAFactor.user_id == user.id,
        UserMFAFactor.enabled_at.isnot(None),
    ).first()
    supabase_mfa_enabled = any(
        isinstance(factor, dict) and factor.get("status") == "verified"
        for factor in (identity.get("factors") or [])
    )
    mfa_verified = False
    mfa_setup_only = False
    if mfa_factor or supabase_mfa_enabled:
        try:
            claims = jwt.decode(
                payload.access_token, options={"verify_signature": False, "verify_exp": False},
                algorithms=["HS256", "ES256", "RS256"],
            )
        except jwt.InvalidTokenError as exc:
            raise HTTPException(401, "Supabase MFA assurance could not be verified") from exc
        if str(claims.get("sub", "")) != supabase_id or claims.get("aal") != "aal2":
            raise HTTPException(403, "This OneCore account requires multi-factor authentication")
        # The Supabase Auth /user request above has already validated the supplied
        # token signature, expiry and subject. Preserve its AAL2 result only in a
        # OneCore-signed claim so the local API can enforce the platform policy.
        mfa_verified = True
    elif platform_role_requires_mfa(user.platform_role):
        mfa_setup_only = True

    try:
        db.flush()
        session = None
        if not mfa_setup_only:
            session = create_user_session(
                db, user, request, auth_method="supabase", mfa_verified=mfa_verified
            )
        db.add(AuditEvent(
            actor_user_id=user.id, organization_id=None,
            action=locals().get("action", "auth.supabase.session_exchanged"),
            resource_type="user", resource_id=str(user.id),
            detail="Supabase Auth identity verified by the configured Supabase Auth service",
        ))
        if mfa_setup_only:
            db.add(AuditEvent(
                actor_user_id=user.id, organization_id=None,
                action="account.mfa.enrollment_required",
                resource_type="user", resource_id=str(user.id),
                detail="Privileged Supabase session restricted to MFA enrollment",
            ))
        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This Supabase identity or email is already linked to another OneCore account") from exc

    return {
        "access_token": create_access_token(
            user.id, user.auth_version,
            mfa_verified=mfa_verified,
            mfa_setup_only=mfa_setup_only,
            session_id=session.id if session else None,
            expires_at=session.expires_at if session else None,
        ),
        "token_type": "bearer",
        "mfa_enrollment_required": mfa_setup_only,
        "user": {
            "id": user.id, "email": user.email, "full_name": user.full_name,
            "platform_role": user.platform_role,
        },
    }
