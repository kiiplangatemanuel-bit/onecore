"""Application-level encryption for healthcare direct identifiers."""
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from app.core.config import settings


def _fernet():
    key = (settings.healthcare_data_encryption_key or "").strip()
    if not key:
        raise HTTPException(503, "Healthcare encryption key is not configured")
    try:
        return Fernet(key.encode("ascii"))
    except Exception:
        raise HTTPException(503, "Healthcare encryption key is invalid")


def encrypt_identifier(value):
    if value is None: return None
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_identifier(value):
    if value is None: return None
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError):
        raise HTTPException(503, "Healthcare patient data cannot be decrypted; verify the configured key")


def patient_number_digest(value):
    key = (settings.healthcare_data_encryption_key or "").strip()
    if not key: raise HTTPException(503, "Healthcare encryption key is not configured")
    return hashlib.sha256((key + ":" + value.strip().casefold()).encode("utf-8")).hexdigest()
