"""Encrypted transactional email enqueueing for account verification and recovery."""
import json
from datetime import datetime, timezone
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.identity_models import IdentityEmailDelivery


def _fernet() -> Fernet:
    key = settings.identity_email_encryption_key.strip()
    if not key:
        raise RuntimeError("IDENTITY_EMAIL_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("IDENTITY_EMAIL_ENCRYPTION_KEY is invalid") from exc


def _validate_delivery_configuration() -> None:
    if not (
        settings.integration_email_enabled
        and settings.email_host.strip()
        and settings.email_from.strip()
        and settings.public_site_url.strip()
    ):
        raise RuntimeError("Transactional email delivery is not configured")
    production = settings.app_env.strip().lower() in {"production", "prod"}
    if production and not settings.public_site_url.strip().startswith("https://"):
        raise RuntimeError("Production transactional email links must use HTTPS")
    if production and not settings.email_use_starttls:
        raise RuntimeError("Production SMTP delivery requires STARTTLS")


def _enqueue(
    db,
    *,
    user_id: int,
    purpose: str,
    token_hash: str,
    recipient_email: str,
    subject: str,
    body: str,
    expires_at: datetime,
) -> IdentityEmailDelivery:
    if purpose not in {"email_verification", "password_reset"}:
        raise ValueError("Unsupported identity email purpose")
    if int(user_id) <= 0 or not token_hash or len(token_hash) != 64:
        raise ValueError("A verified account ID and token digest are required")
    _validate_delivery_configuration()
    cipher = _fernet()
    payload = {
        "recipient_email": recipient_email.strip().lower(),
        "subject": subject,
        "body": body,
    }
    if not payload["recipient_email"] or len(payload["recipient_email"]) > 320:
        raise ValueError("A valid recipient email address is required")
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ciphertext = cipher.encrypt(encoded).decode("ascii")
    now = datetime.now(timezone.utc)
    expiry = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    if expiry <= now:
        raise ValueError("Identity email expiry must be in the future")
    row = IdentityEmailDelivery(
        user_id=int(user_id),
        purpose=purpose,
        event_key=f"{purpose}:{token_hash}",
        payload_ciphertext=ciphertext,
        status="pending",
        attempts=0,
        next_attempt_at=now,
        expires_at=expiry,
        last_error="",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    return row


def queue_verification_email(
    db,
    *,
    user_id: int,
    email: str,
    full_name: str,
    token: str,
    token_hash: str,
    expires_at: datetime,
) -> IdentityEmailDelivery:
    verify_url = (
        settings.public_site_url.rstrip("/")
        + "/verify-email?token="
        + quote(token, safe="")
    )
    body = (
        f"Hello {full_name},\n\n"
        "Thank you for registering your organization with OneCore. "
        "Verify your email address within 24 hours using this link:\n\n"
        f"{verify_url}\n\n"
        "If you did not request this registration, you can ignore this email."
    )
    return _enqueue(
        db,
        user_id=user_id,
        purpose="email_verification",
        token_hash=token_hash,
        recipient_email=email,
        subject="Verify your OneCore account",
        body=body,
        expires_at=expires_at,
    )


def queue_password_reset_email(
    db,
    *,
    user_id: int,
    email: str,
    full_name: str,
    token: str,
    token_hash: str,
    expires_at: datetime,
) -> IdentityEmailDelivery:
    # The secret remains in the URL fragment and is not sent to web-server access logs.
    reset_url = (
        settings.public_site_url.rstrip("/")
        + "/reset-password#token="
        + quote(token, safe="")
    )
    body = (
        f"Hello {full_name or 'OneCore user'},\n\n"
        "A password reset was requested for your OneCore account. "
        "Use this link within 30 minutes to choose a new password:\n\n"
        f"{reset_url}\n\n"
        "If you did not request this change, ignore this email. "
        "Your current password will remain active."
    )
    return _enqueue(
        db,
        user_id=user_id,
        purpose="password_reset",
        token_hash=token_hash,
        recipient_email=email,
        subject="Reset your OneCore password",
        body=body,
        expires_at=expires_at,
    )


def decrypt_identity_email_payload(row: IdentityEmailDelivery) -> dict[str, str]:
    """Decrypt a delivery only inside the trusted email worker or a controlled test."""
    try:
        raw = _fernet().decrypt(row.payload_ciphertext.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (InvalidToken, UnicodeError, ValueError, TypeError) as exc:
        raise RuntimeError("Identity email payload cannot be decrypted") from exc
    if not isinstance(payload, dict) or set(payload) != {"recipient_email", "subject", "body"}:
        raise RuntimeError("Identity email payload has an invalid shape")
    if not all(isinstance(payload[key], str) for key in payload):
        raise RuntimeError("Identity email payload fields must be text")
    return payload
