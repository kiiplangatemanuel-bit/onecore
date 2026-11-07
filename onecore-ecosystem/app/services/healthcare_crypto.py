import base64
import hashlib
import json
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from app.core.config import settings


def _fernet():
    configured=(settings.healthcare_encryption_key or "").strip()
    if configured:
        try:
            return Fernet(configured.encode("ascii"))
        except Exception:
            raise RuntimeError("HEALTHCARE_ENCRYPTION_KEY must be a valid Fernet key")
    # Domain-separated derivation keeps development usable; production should set
    # a separately managed key and rotate it through a controlled re-encryption job.
    if (settings.app_env or "").lower() in {"production","prod"}:
        raise RuntimeError("HEALTHCARE_ENCRYPTION_KEY must be configured separately in production")
    secret=(settings.secret_key or "").strip()
    if (not secret or len(secret)<32 or secret=="unsafe-development-key-change-me"
        or "replace-with" in secret.lower() or "change-me" in secret.lower()):
        raise RuntimeError("Set a strong SECRET_KEY and HEALTHCARE_ENCRYPTION_KEY before storing health data")
    seed=secret.encode("utf-8")
    digest=hashlib.sha256(b"onecore-healthcare-field-encryption-v1:"+seed).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_health_data(value: dict) -> str:
    raw=json.dumps(value,ensure_ascii=False,separators=(",",":"),sort_keys=True).encode("utf-8")
    return _fernet().encrypt(raw).decode("ascii")


def decrypt_health_data(value: str) -> dict:
    try:
        return json.loads(_fernet().decrypt(value.encode("ascii")).decode("utf-8"))
    except (InvalidToken, ValueError, UnicodeError):
        raise HTTPException(503,"Clinical data cannot be decrypted; verify the configured encryption key")
