import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.models import AuditEvent, EmailVerification, Membership, Organization, PasswordResetToken, PortalAuthorizationCode, User
from app.core.identity_models import IdentityEmailDelivery, UserSession
from app.core.schemas import EmailVerificationIn, OrganizationRegistrationIn, PasswordResetRequestIn, PasswordResetConfirmIn
from app.core.security import hash_password, set_verified_user_context
from app.services.identity_email import queue_password_reset_email, queue_verification_email

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
logger = logging.getLogger(__name__)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@router.post("/register-organization", status_code=202)
def register_organization(payload: OrganizationRegistrationIn, db: Session = Depends(get_db)):
    email = str(payload.email).lower()
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(409, "An account with this email already exists. Sign in or contact support.")
    if db.query(Organization).filter(Organization.slug == payload.organization_slug).first():
        raise HTTPException(409, "Organization URL is already in use. Choose another slug.")

    token = secrets.token_urlsafe(36)
    user = User(
        email=email, full_name=payload.full_name.strip(), phone=payload.phone.strip(),
        password_hash=hash_password(payload.password), is_active=False,
        platform_role="customer",
    )
    organization = Organization(
        name=payload.organization_name.strip(), slug=payload.organization_slug,
        industry=payload.industry, country=payload.country, currency=payload.currency,
        timezone=payload.timezone, is_active=True,
    )
    try:
        db.add(user)
        db.add(organization)
        db.flush()
        # The user ID is assigned by the database during flush; persist it as
        # the organization owner before the RLS-protected first membership insert.
        organization.owner_user_id = user.id
        db.flush()
        set_verified_user_context(db, user.id)
        db.add(Membership(
            user_id=user.id, organization_id=organization.id,
            role="org_admin", branch_scope="*", is_active=True,
        ))
        verification_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        verification_token_hash = _token_hash(token)
        db.add(EmailVerification(
            user_id=user.id, token_hash=verification_token_hash,
            expires_at=verification_expires_at,
        ))
        queue_verification_email(
            db,
            user_id=user.id,
            email=email,
            full_name=payload.full_name,
            token=token,
            token_hash=verification_token_hash,
            expires_at=verification_expires_at,
        )
        db.add(AuditEvent(
            actor_user_id=user.id, organization_id=organization.id,
            action="organization.registration.requested",
            resource_type="organization", resource_id=str(organization.id),
        ))
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account or organization with these details already exists.")
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(503, "Verification email delivery is not configured. Please try again later.") from exc

    return {
        "status": "verification_required",
        "message": "Check your email to verify your account before signing in.",
        "organization": {"name": organization.name, "slug": organization.slug},
    }


@router.post("/verify-email")
def verify_email(payload: EmailVerificationIn, db: Session = Depends(get_db)):
    verification = db.query(EmailVerification).filter_by(
        token_hash=_token_hash(payload.token)
    ).with_for_update().first()
    if not verification or verification.consumed_at is not None:
        raise HTTPException(400, "Verification link is invalid or has already been used.")
    expires_at = verification.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(400, "Verification link has expired. Contact support for a new link.")
    user = db.get(User, verification.user_id)
    if not user:
        raise HTTPException(400, "Verification account could not be found.")
    set_verified_user_context(db, user.id)
    user.is_active = True
    verification.consumed_at = datetime.now(timezone.utc)
    db.query(IdentityEmailDelivery).filter(
        IdentityEmailDelivery.user_id == user.id,
        IdentityEmailDelivery.purpose == "email_verification",
        IdentityEmailDelivery.status.in_(["pending", "sending"]),
    ).update(
        {
            IdentityEmailDelivery.status: "cancelled",
            IdentityEmailDelivery.last_error: "token_consumed",
            IdentityEmailDelivery.updated_at: datetime.now(timezone.utc),
        },
        synchronize_session=False,
    )
    membership = db.query(Membership).filter_by(user_id=user.id, is_active=True).first()
    db.add(AuditEvent(
        actor_user_id=user.id,
        organization_id=membership.organization_id if membership else None,
        action="account.email_verified", resource_type="user", resource_id=str(user.id),
    ))
    db.commit()
    return {"status": "verified", "message": "Email verified. You can now sign in to OneCore."}



@router.post("/password-reset/request", status_code=202)
def request_password_reset(payload: PasswordResetRequestIn, db: Session = Depends(get_db)):
    """Return the same response for existing and unknown accounts."""
    generic_response = {
        "status": "accepted",
        "message": "If an active OneCore account matches that email, a password reset link will be sent.",
    }
    email = str(payload.email).strip().lower()
    user = db.query(User).filter(
        func.lower(User.email) == email,
        User.is_active.is_(True),
    ).first()
    if not user:
        return generic_response

    now = datetime.now(timezone.utc)
    raw_token = secrets.token_urlsafe(36)
    token_hash = _token_hash(raw_token)
    expires_at = now + timedelta(minutes=30)
    try:
        set_verified_user_context(db, user.id)
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.consumed_at.is_(None),
        ).update(
            {PasswordResetToken.consumed_at: now},
            synchronize_session=False,
        )
        db.query(IdentityEmailDelivery).filter(
            IdentityEmailDelivery.user_id == user.id,
            IdentityEmailDelivery.purpose == "password_reset",
            IdentityEmailDelivery.status.in_(["pending", "sending"]),
        ).update(
            {
                IdentityEmailDelivery.status: "cancelled",
                IdentityEmailDelivery.last_error: "superseded",
                IdentityEmailDelivery.updated_at: now,
            },
            synchronize_session=False,
        )
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        ))
        db.add(AuditEvent(
            actor_user_id=user.id,
            action="account.password_reset.requested",
            resource_type="user",
            resource_id=str(user.id),
        ))
        queue_password_reset_email(
            db,
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            token=raw_token,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db.commit()
    except RuntimeError as exc:
        db.rollback()
        logger.warning(
            "Password reset email could not be queued for user id %s (%s)",
            user.id,
            type(exc).__name__,
        )
    return generic_response


@router.post("/password-reset/confirm")
def confirm_password_reset(payload: PasswordResetConfirmIn, db: Session = Depends(get_db)):
    row = db.query(PasswordResetToken).filter_by(
        token_hash=_token_hash(payload.token)
    ).with_for_update().first()
    now = datetime.now(timezone.utc)
    if not row or row.consumed_at is not None:
        raise HTTPException(400, "Password reset link is invalid or has expired.")
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise HTTPException(400, "Password reset link is invalid or has expired.")
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(400, "Password reset link is invalid or has expired.")

    set_verified_user_context(db, user.id)
    user.password_hash = hash_password(payload.new_password)
    user.auth_version = int(user.auth_version or 0) + 1
    row.consumed_at = now
    db.query(UserSession).filter(
        UserSession.user_id == user.id,
        UserSession.revoked_at.is_(None),
    ).update(
        {UserSession.revoked_at: now, UserSession.revoked_reason: "password_reset"},
        synchronize_session=False,
    )
    db.query(PortalAuthorizationCode).filter(
        PortalAuthorizationCode.user_id == user.id,
        PortalAuthorizationCode.consumed_at.is_(None),
    ).update(
        {PortalAuthorizationCode.consumed_at: now},
        synchronize_session=False,
    )
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.id != row.id,
        PasswordResetToken.consumed_at.is_(None),
    ).update(
        {PasswordResetToken.consumed_at: now},
        synchronize_session=False,
    )
    db.query(IdentityEmailDelivery).filter(
        IdentityEmailDelivery.user_id == user.id,
        IdentityEmailDelivery.purpose == "password_reset",
        IdentityEmailDelivery.status.in_(["pending", "sending"]),
    ).update(
        {
            IdentityEmailDelivery.status: "cancelled",
            IdentityEmailDelivery.last_error: "token_consumed",
            IdentityEmailDelivery.updated_at: now,
        },
        synchronize_session=False,
    )
    db.add(AuditEvent(
        actor_user_id=user.id,
        action="account.password_reset.completed",
        resource_type="user",
        resource_id=str(user.id),
    ))
    db.commit()
    return {"status": "password_reset", "message": "Password updated. Sign in again with your new password."}
