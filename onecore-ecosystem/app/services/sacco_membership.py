"""Encryption, identity fingerprinting and deterministic transaction fingerprints for SACCO."""
import hashlib
import hmac
import json
import re
from cryptography.fernet import Fernet, InvalidToken
from app.core.config import settings


class KYCConfigurationError(RuntimeError):
    """Raised when required KYC cryptographic configuration is unavailable."""


def _fernet() -> Fernet:
    key = settings.sacco_kyc_encryption_key.strip()
    if not key:
        raise KYCConfigurationError("SACCO KYC encryption is not configured")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise KYCConfigurationError("SACCO KYC encryption configuration is invalid") from exc


def _hmac_key() -> bytes:
    key = settings.sacco_kyc_hmac_key.strip().encode("utf-8")
    if len(key) < 32:
        raise KYCConfigurationError("SACCO KYC fingerprinting is not configured")
    return key


def normalize_identity_number(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()
    if not 6 <= len(normalized) <= 20:
        raise ValueError("Identity number must contain 6 to 20 letters or digits")
    return normalized


def identity_fingerprint(national_id: str) -> str:
    return hmac.new(_hmac_key(), normalize_identity_number(national_id).encode("utf-8"), hashlib.sha256).hexdigest()


def request_fingerprint(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(_hmac_key(), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def transaction_fingerprint(payload: dict) -> str:
    """Hash a canonical, non-secret financial request for idempotency comparison."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def encrypt_kyc_payload(payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _fernet().encrypt(serialized.encode("utf-8")).decode("ascii")


def decrypt_kyc_payload(ciphertext: str) -> dict:
    try:
        raw = _fernet().decrypt(ciphertext.encode("ascii"))
        return json.loads(raw.decode("utf-8"))
    except InvalidToken as exc:
        raise KYCConfigurationError("Stored KYC data cannot be decrypted; verify the configured key") from exc
