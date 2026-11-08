import hashlib
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.models import AuditEvent, EmailVerification, Membership, Organization, User
from app.core.schemas import EmailVerificationIn, OrganizationRegistrationIn
from app.core.security import current_user, hash_password

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _send_verification_email(email: str, full_name: str, token: str):
    required = (
        settings.integration_email_enabled and settings.email_host
        and settings.email_from and settings.public_site_url
    )
    if not required:
        raise HTTPException(
            status_code=503,
            detail="Organization registration is temporarily unavailable because verification email is not configured.",
        )
    verify_url = settings.public_site_url.rstrip("/") + "/verify-email?token=" + token
    message = EmailMessage()
    message["Subject"] = "Verify your OneCore account"
    message["From"] = settings.email_from
    message["To"] = email
    message.set_content(
        f"Hello {full_name},\n\n"
        "Thank you for registering your organization with OneCore. "
        "Verify your email address within 24 hours using this link:\n\n"
        f"{verify_url}\n\n"
        "If you did not request this registration, you can ignore this email."
    )
    with smtplib.SMTP(settings.email_host, settings.email_port, timeout=15) as smtp:
        if settings.email_use_starttls:
            smtp.starttls()
        if settings.email_username:
            smtp.login(settings.email_username, settings.email_password)
        smtp.send_message(message)


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
        db.add(Membership(
            user_id=user.id, organization_id=organization.id,
            role="org_admin", branch_scope="*", is_active=True,
        ))
        db.add(EmailVerification(
            user_id=user.id, token_hash=_token_hash(token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        ))
        _send_verification_email(email, payload.full_name, token)
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
    except (OSError, smtplib.SMTPException) as exc:
        db.rollback()
        raise HTTPException(503, "Verification email could not be sent. Please try again later.") from exc

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
    user.is_active = True
    verification.consumed_at = datetime.now(timezone.utc)
    membership = db.query(Membership).filter_by(user_id=user.id, is_active=True).first()
    db.add(AuditEvent(
        actor_user_id=user.id,
        organization_id=membership.organization_id if membership else None,
        action="account.email_verified", resource_type="user", resource_id=str(user.id),
    ))
    db.commit()
    return {"status": "verified", "message": "Email verified. You can now sign in to OneCore."}



class CompleteOrganizationRegistrationIn(BaseModel):
    organization_name: str = Field(min_length=2, max_length=200)
    organization_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,118}[a-z0-9]$")
    industry: str = Field(default="general", max_length=100)
    country: str = Field(default="KE", pattern=r"^[A-Z]{2}$")
    currency: str = Field(default="KES", pattern=r"^[A-Z]{3}$")
    timezone: str = Field(default="Africa/Nairobi", max_length=80)


@router.post("/complete-organization-registration", status_code=201)
def complete_organization_registration(
    payload: CompleteOrganizationRegistrationIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if db.query(Membership).filter_by(user_id=user.id, is_active=True).first():
        raise HTTPException(409, "This account already belongs to an active organization.")
    if db.query(Organization).filter_by(slug=payload.organization_slug).first():
        raise HTTPException(409, "Organization URL is already in use. Choose another slug.")
    organization = Organization(
        name=payload.organization_name.strip(), slug=payload.organization_slug,
        industry=payload.industry, country=payload.country, currency=payload.currency,
        timezone=payload.timezone, is_active=True,
    )
    try:
        db.add(organization)
        db.flush()
        db.add(Membership(
            user_id=user.id, organization_id=organization.id,
            role="org_admin", branch_scope="*", is_active=True,
        ))
        db.add(AuditEvent(
            actor_user_id=user.id, organization_id=organization.id,
            action="organization.registration.completed",
            resource_type="organization", resource_id=str(organization.id),
        ))
        db.commit()
        db.refresh(organization)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Organization URL is already in use. Choose another slug.")
    return {"organization": {"id": organization.id, "name": organization.name, "slug": organization.slug}, "role": "org_admin"}
