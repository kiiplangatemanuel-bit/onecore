import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.models import AuditEvent, MFAChallenge, MFARecoveryCode, PortalAuthorizationCode, User, UserMFAFactor
from app.core.security import create_access_token, current_user, current_user_for_mfa_setup, verify_password

router = APIRouter(prefix="/api/v1/auth/mfa", tags=["authentication"])
CHALLENGE_SECONDS = 300
MAX_CHALLENGE_ATTEMPTS = 5
RECOVERY_CODE_COUNT = 10


class MFAEnrollIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class MFAConfirmIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class MFAChallengeIn(BaseModel):
    challenge_token: str = Field(min_length=32, max_length=128)
    code: str = Field(min_length=6, max_length=64)


class MFASensitiveActionIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=6, max_length=64)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fernet() -> Fernet:
    key = settings.mfa_encryption_key.strip()
    if not key:
        raise HTTPException(status_code=503, detail="MFA is unavailable until MFA_ENCRYPTION_KEY is configured.")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise HTTPException(status_code=503, detail="MFA_ENCRYPTION_KEY is invalid; configure a valid Fernet key.") from exc


def _new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _totp_code(secret: str, timestamp: float | None = None) -> str:
    """Return the RFC 6238 six-digit SHA-1 TOTP for a given timestamp."""
    counter = int((time.time() if timestamp is None else timestamp) // 30)
    padding = "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(secret + padding, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF
    return f"{binary % 1_000_000:06d}"


def _matching_totp_step(secret: str, code: str, timestamp: float, last_used_step: int | None) -> int | None:
    if not re.fullmatch(r"\d{6}", code):
        return None
    current_step = int(timestamp // 30)
    for step in (current_step - 1, current_step, current_step + 1):
        if step < 0 or (last_used_step is not None and step <= last_used_step):
            continue
        expected = _totp_code(secret, step * 30)
        if hmac.compare_digest(expected, code):
            return step
    return None


def _decrypt_secret(factor: UserMFAFactor) -> str:
    try:
        return _fernet().decrypt(factor.secret_ciphertext.encode("ascii")).decode("ascii")
    except InvalidToken as exc:
        raise HTTPException(status_code=503, detail="The stored MFA seed cannot be decrypted; contact the platform administrator.") from exc


def _audit(db: Session, user: User, action: str, detail: str = "") -> None:
    db.add(AuditEvent(
        actor_user_id=user.id,
        action=action,
        resource_type="user_security",
        resource_id=str(user.id),
        detail=detail,
    ))


def _revoke_portal_handoffs(db: Session, user_id: int, now: datetime) -> None:
    db.query(PortalAuthorizationCode).filter(
        PortalAuthorizationCode.user_id == user_id,
        PortalAuthorizationCode.consumed_at.is_(None),
    ).update({PortalAuthorizationCode.consumed_at: now}, synchronize_session=False)
    db.query(MFAChallenge).filter(
        MFAChallenge.user_id == user_id,
        MFAChallenge.consumed_at.is_(None),
    ).update({MFAChallenge.consumed_at: now}, synchronize_session=False)


def _revoke_recovery_codes(db: Session, user_id: int, now: datetime) -> None:
    db.query(MFARecoveryCode).filter(
        MFARecoveryCode.user_id == user_id,
        MFARecoveryCode.used_at.is_(None),
        MFARecoveryCode.revoked_at.is_(None),
    ).update({MFARecoveryCode.revoked_at: now}, synchronize_session=False)


def _new_recovery_codes(db: Session, user_id: int, now: datetime) -> list[str]:
    codes: list[str] = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(8).upper()
        display = "-".join(raw[index:index + 4] for index in range(0, 16, 4))
        db.add(MFARecoveryCode(user_id=user_id, code_hash=_digest(raw), created_at=now))
        codes.append(display)
    return codes


def _verify_and_consume_code(db: Session, user: User, factor: UserMFAFactor, code: str, now: datetime) -> bool:
    normalized = re.sub(r"[\s-]", "", code).upper()
    if re.fullmatch(r"[A-F0-9]{16}", normalized):
        recovery = db.query(MFARecoveryCode).filter_by(
            user_id=user.id, code_hash=_digest(normalized)
        ).with_for_update().first()
        if recovery and recovery.used_at is None and recovery.revoked_at is None:
            recovery.used_at = now
            return True
    secret = _decrypt_secret(factor)
    step = _matching_totp_step(secret, code.strip(), now.timestamp(), factor.last_used_step)
    if step is None:
        return False
    factor.last_used_step = step
    return True


def issue_mfa_challenge(db: Session, user: User) -> dict:
    """Issue a digest-stored, five-minute challenge after password verification."""
    now = _now()
    db.query(MFAChallenge).filter(
        MFAChallenge.user_id == user.id,
        MFAChallenge.consumed_at.is_(None),
    ).update({MFAChallenge.consumed_at: now}, synchronize_session=False)
    raw_token = secrets.token_urlsafe(32)
    db.add(MFAChallenge(
        user_id=user.id,
        auth_version=int(user.auth_version or 0),
        token_hash=_digest(raw_token),
        expires_at=now + timedelta(seconds=CHALLENGE_SECONDS),
        attempts=0,
    ))
    _audit(db, user, "account.mfa.challenge_issued")
    db.commit()
    return {"mfa_required": True, "challenge_token": raw_token, "expires_in": CHALLENGE_SECONDS, "methods": ["totp", "recovery_code"]}


@router.get("/status")
def mfa_status(user: User = Depends(current_user_for_mfa_setup), db: Session = Depends(get_db)):
    factor = db.query(UserMFAFactor).filter_by(user_id=user.id).first()
    enabled = bool(factor and factor.enabled_at is not None)
    remaining = db.query(MFARecoveryCode).filter(
        MFARecoveryCode.user_id == user.id,
        MFARecoveryCode.used_at.is_(None),
        MFARecoveryCode.revoked_at.is_(None),
    ).count()
    return {"enabled": enabled, "setup_pending": bool(factor and factor.enabled_at is None), "recovery_codes_remaining": remaining}


@router.post("/enroll")
def start_mfa_enrollment(payload: MFAEnrollIn, user: User = Depends(current_user_for_mfa_setup), db: Session = Depends(get_db)):
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(403, "Password re-authentication failed.")
    cipher = _fernet()
    now = _now()
    factor = db.query(UserMFAFactor).filter_by(user_id=user.id).with_for_update().first()
    if factor and factor.enabled_at is not None:
        raise HTTPException(409, "MFA is already enabled for this account.")
    secret = _new_secret()
    encrypted = cipher.encrypt(secret.encode("ascii")).decode("ascii")
    if factor:
        factor.secret_ciphertext = encrypted
        factor.pending_expires_at = now + timedelta(minutes=10)
        factor.last_used_step = None
    else:
        db.add(UserMFAFactor(
            user_id=user.id,
            secret_ciphertext=encrypted,
            pending_expires_at=now + timedelta(minutes=10),
        ))
    _audit(db, user, "account.mfa.enrollment_started")
    db.commit()
    label = quote("OneCore:" + user.email, safe="")
    query = urlencode({"secret": secret, "issuer": "OneCore", "algorithm": "SHA1", "digits": "6", "period": "30"})
    return {"status": "pending", "secret": secret, "otpauth_uri": f"otpauth://totp/{label}?{query}", "expires_in": 600}


@router.post("/confirm")
def confirm_mfa_enrollment(payload: MFAConfirmIn, user: User = Depends(current_user_for_mfa_setup), db: Session = Depends(get_db)):
    now = _now()
    factor = db.query(UserMFAFactor).filter_by(user_id=user.id).with_for_update().first()
    if not factor or factor.enabled_at is not None:
        raise HTTPException(409, "No pending MFA enrollment exists.")
    if not factor.pending_expires_at or _utc(factor.pending_expires_at) <= now:
        db.delete(factor)
        db.commit()
        raise HTTPException(400, "MFA enrollment expired. Start again.")
    secret = _decrypt_secret(factor)
    step = _matching_totp_step(secret, payload.code, now.timestamp(), factor.last_used_step)
    if step is None:
        raise HTTPException(400, "Authenticator code is invalid or outside the allowed time window.")
    factor.enabled_at = now
    factor.pending_expires_at = None
    factor.last_used_step = step
    _revoke_recovery_codes(db, user.id, now)
    codes = _new_recovery_codes(db, user.id, now)
    user.auth_version = int(user.auth_version or 0) + 1
    _revoke_portal_handoffs(db, user.id, now)
    _audit(db, user, "account.mfa.enabled")
    db.commit()
    return {"status": "enabled", "recovery_codes": codes, "message": "MFA enabled. Save these recovery codes now; they will not be shown again."}


@router.post("/challenge")
def complete_mfa_challenge(payload: MFAChallengeIn, db: Session = Depends(get_db)):
    now = _now()
    row = db.query(MFAChallenge).filter_by(token_hash=_digest(payload.challenge_token)).with_for_update().first()
    if not row or row.consumed_at is not None:
        raise HTTPException(401, "MFA challenge is invalid or expired.")
    if _utc(row.expires_at) <= now or row.attempts >= MAX_CHALLENGE_ATTEMPTS:
        row.consumed_at = now
        db.commit()
        raise HTTPException(401, "MFA challenge is invalid or expired.")
    user = db.get(User, row.user_id)
    factor = db.query(UserMFAFactor).filter_by(user_id=row.user_id).with_for_update().first()
    if not user or not user.is_active or int(user.auth_version or 0) != int(row.auth_version) or not factor or factor.enabled_at is None:
        row.consumed_at = now
        db.commit()
        raise HTTPException(401, "MFA challenge is invalid or expired.")
    if _verify_and_consume_code(db, user, factor, payload.code, now):
        row.consumed_at = now
        _audit(db, user, "account.mfa.challenge_succeeded")
        db.commit()
        return {"access_token": create_access_token(user.id, user.auth_version), "token_type": "bearer"}
    row.attempts = int(row.attempts or 0) + 1
    if row.attempts >= MAX_CHALLENGE_ATTEMPTS:
        row.consumed_at = now
    _audit(db, user, "account.mfa.challenge_failed", f"attempt={row.attempts}")
    db.commit()
    raise HTTPException(401, "Authenticator or recovery code is invalid.")


@router.post("/recovery-codes/rotate")
def rotate_mfa_recovery_codes(payload: MFASensitiveActionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(403, "Password re-authentication failed.")
    now = _now()
    factor = db.query(UserMFAFactor).filter_by(user_id=user.id).with_for_update().first()
    if not factor or factor.enabled_at is None:
        raise HTTPException(409, "MFA is not enabled for this account.")
    if not _verify_and_consume_code(db, user, factor, payload.code, now):
        raise HTTPException(400, "Authenticator or recovery code is invalid.")
    _revoke_recovery_codes(db, user.id, now)
    codes = _new_recovery_codes(db, user.id, now)
    _audit(db, user, "account.mfa.recovery_codes_rotated")
    db.commit()
    return {"recovery_codes": codes, "message": "Previous recovery codes have been revoked."}


@router.post("/disable")
def disable_mfa(payload: MFASensitiveActionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(403, "Password re-authentication failed.")
    now = _now()
    factor = db.query(UserMFAFactor).filter_by(user_id=user.id).with_for_update().first()
    if not factor or factor.enabled_at is None:
        raise HTTPException(409, "MFA is not enabled for this account.")
    if not _verify_and_consume_code(db, user, factor, payload.code, now):
        raise HTTPException(400, "Authenticator or recovery code is invalid.")
    _revoke_recovery_codes(db, user.id, now)
    db.delete(factor)
    user.auth_version = int(user.auth_version or 0) + 1
    _revoke_portal_handoffs(db, user.id, now)
    _audit(db, user, "account.mfa.disabled")
    db.commit()
    return {"status": "disabled", "message": "MFA disabled. Sign in again to refresh your account session."}
