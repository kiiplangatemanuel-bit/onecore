import hashlib
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.api.auth_mfa as mfa
from app.api.auth_mfa import MFAChallengeIn, MFAConfirmIn, MFAEnrollIn, MFASensitiveActionIn
from app.api.auth_mfa import _totp_code, complete_mfa_challenge, confirm_mfa_enrollment, disable_mfa, issue_mfa_challenge, start_mfa_enrollment
from app.core.config import settings
from app.core.database import Base
from app.core.models import AuditEvent, MFAChallenge, MFARecoveryCode, PortalAuthorizationCode, User, UserMFAFactor
from app.core.security import current_user, hash_password
from app.api.routes import login


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, AuditEvent.__table__, MFAChallenge.__table__,
        MFARecoveryCode.__table__, PortalAuthorizationCode.__table__, UserMFAFactor.__table__,
    ])
    return engine


def _user(db):
    user = User(email="mfa-member@example.com", full_name="MFA Member",
                password_hash=hash_password("correct-password"), is_active=True)
    db.add(user)
    db.commit()
    return user


def _enable(db, user):
    pending = start_mfa_enrollment(MFAEnrollIn(password="correct-password"), user, db)
    code = _totp_code(pending["secret"], mfa._now().timestamp())
    result = confirm_mfa_enrollment(MFAConfirmIn(code=code), user, db)
    db.refresh(user)
    return pending, result


def test_totp_matches_rfc6238_sha1_six_digit_vector():
    assert _totp_code("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 59) == "287082"


def test_enrollment_encrypts_seed_and_returns_one_time_recovery_codes(monkeypatch):
    monkeypatch.setattr(settings, "mfa_encryption_key", mfa.Fernet.generate_key().decode())
    engine = _engine()
    with Session(engine) as db:
        user = _user(db)
        pending, result = _enable(db, user)
        factor = db.query(UserMFAFactor).filter_by(user_id=user.id).one()
        rows = db.query(MFARecoveryCode).filter_by(user_id=user.id).all()
        assert pending["otpauth_uri"].startswith("otpauth://totp/")
        assert pending["secret"] not in factor.secret_ciphertext
        assert result["status"] == "enabled"
        assert len(result["recovery_codes"]) == 10
        assert len(rows) == 10
        assert all(row.code_hash == hashlib.sha256(code.replace("-", "").encode()).hexdigest()
                   for row, code in zip(rows, result["recovery_codes"]))
        assert user.auth_version == 1
        assert factor.enabled_at is not None
    engine.dispose()


def test_password_login_returns_challenge_and_only_second_factor_mints_access_token(monkeypatch):
    monkeypatch.setattr(settings, "mfa_encryption_key", mfa.Fernet.generate_key().decode())
    engine = _engine()
    with Session(engine) as db:
        user = _user(db)
        fixed_now = mfa._now()
        monkeypatch.setattr(mfa, "_now", lambda: fixed_now)
        _enable(db, user)
        form = OAuth2PasswordRequestForm(username=user.email, password="correct-password", scope="")
        login_result = login(form, db)
        assert login_result["mfa_required"] is True
        assert "access_token" not in login_result
        factor = db.query(UserMFAFactor).filter_by(user_id=user.id).one()
        code = _totp_code(mfa._decrypt_secret(factor), fixed_now.timestamp())
        result = complete_mfa_challenge(MFAChallengeIn(
            challenge_token=login_result["challenge_token"], code=code
        ), db)
        assert result["token_type"] == "bearer"
        assert current_user(token=result["access_token"], db=db).id == user.id
        row = db.query(MFAChallenge).filter_by(user_id=user.id).one()
        assert row.consumed_at is not None
    engine.dispose()


def test_recovery_code_is_single_use(monkeypatch):
    monkeypatch.setattr(settings, "mfa_encryption_key", mfa.Fernet.generate_key().decode())
    engine = _engine()
    with Session(engine) as db:
        user = _user(db)
        _, enabled = _enable(db, user)
        recovery_code = enabled["recovery_codes"][0]
        challenge = issue_mfa_challenge(db, user)
        complete_mfa_challenge(MFAChallengeIn(
            challenge_token=challenge["challenge_token"], code=recovery_code
        ), db)
        digest = hashlib.sha256(recovery_code.replace("-", "").encode()).hexdigest()
        row = db.query(MFARecoveryCode).filter_by(user_id=user.id, code_hash=digest).one()
        assert row.used_at is not None
        second = issue_mfa_challenge(db, user)
        with pytest.raises(HTTPException) as replay:
            complete_mfa_challenge(MFAChallengeIn(
                challenge_token=second["challenge_token"], code=recovery_code
            ), db)
        assert replay.value.status_code == 401
    engine.dispose()


def test_totp_time_step_cannot_be_replayed_across_challenges(monkeypatch):
    monkeypatch.setattr(settings, "mfa_encryption_key", mfa.Fernet.generate_key().decode())
    engine = _engine()
    with Session(engine) as db:
        user = _user(db)
        fixed_now = mfa._now()
        monkeypatch.setattr(mfa, "_now", lambda: fixed_now)
        _enable(db, user)
        factor = db.query(UserMFAFactor).filter_by(user_id=user.id).one()
        code = _totp_code(mfa._decrypt_secret(factor), fixed_now.timestamp())
        first = issue_mfa_challenge(db, user)
        complete_mfa_challenge(MFAChallengeIn(challenge_token=first["challenge_token"], code=code), db)
        second = issue_mfa_challenge(db, user)
        with pytest.raises(HTTPException) as replay:
            complete_mfa_challenge(MFAChallengeIn(challenge_token=second["challenge_token"], code=code), db)
        assert replay.value.status_code == 401
    engine.dispose()


def test_challenge_locks_after_five_invalid_attempts(monkeypatch):
    monkeypatch.setattr(settings, "mfa_encryption_key", mfa.Fernet.generate_key().decode())
    engine = _engine()
    with Session(engine) as db:
        user = _user(db)
        _enable(db, user)
        challenge = issue_mfa_challenge(db, user)
        for _ in range(5):
            with pytest.raises(HTTPException) as invalid:
                complete_mfa_challenge(MFAChallengeIn(
                    challenge_token=challenge["challenge_token"], code="not-a-valid-code"
                ), db)
            assert invalid.value.status_code == 401
        row = db.query(MFAChallenge).filter_by(token_hash=hashlib.sha256(
            challenge["challenge_token"].encode()
        ).hexdigest()).one()
        assert row.attempts == 5
        assert row.consumed_at is not None
    engine.dispose()


def test_disable_requires_password_and_second_factor_and_revokes_access(monkeypatch):
    monkeypatch.setattr(settings, "mfa_encryption_key", mfa.Fernet.generate_key().decode())
    engine = _engine()
    with Session(engine) as db:
        user = _user(db)
        fixed_now = mfa._now()
        monkeypatch.setattr(mfa, "_now", lambda: fixed_now)
        _enable(db, user)
        old_access_token = mfa.create_access_token(user.id, user.auth_version)
        factor = db.query(UserMFAFactor).filter_by(user_id=user.id).one()
        code = _totp_code(mfa._decrypt_secret(factor), fixed_now.timestamp())
        result = disable_mfa(MFASensitiveActionIn(password="correct-password", code=code), user, db)
        db.refresh(user)
        assert result["status"] == "disabled"
        assert user.auth_version == 2
        assert db.query(UserMFAFactor).filter_by(user_id=user.id).count() == 0
        assert db.query(MFARecoveryCode).filter_by(user_id=user.id).filter(
            MFARecoveryCode.revoked_at.is_(None)
        ).count() == 0
        with pytest.raises(HTTPException) as revoked:
            current_user(token=old_access_token, db=db)
        assert revoked.value.status_code == 401
    engine.dispose()


def test_enrollment_fails_closed_without_encryption_key(monkeypatch):
    monkeypatch.setattr(settings, "mfa_encryption_key", "")
    engine = _engine()
    with Session(engine) as db:
        user = _user(db)
        with pytest.raises(HTTPException) as blocked:
            start_mfa_enrollment(MFAEnrollIn(password="correct-password"), user, db)
        assert blocked.value.status_code == 503
        assert db.query(UserMFAFactor).count() == 0
    engine.dispose()


def test_pending_enrollment_expires(monkeypatch):
    monkeypatch.setattr(settings, "mfa_encryption_key", mfa.Fernet.generate_key().decode())
    engine = _engine()
    with Session(engine) as db:
        user = _user(db)
        pending = start_mfa_enrollment(MFAEnrollIn(password="correct-password"), user, db)
        factor = db.query(UserMFAFactor).filter_by(user_id=user.id).one()
        factor.pending_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        with pytest.raises(HTTPException) as expired:
            confirm_mfa_enrollment(MFAConfirmIn(code=_totp_code(pending["secret"], time.time())), user, db)
        assert expired.value.status_code == 400
        assert db.query(UserMFAFactor).filter_by(user_id=user.id).count() == 0
    engine.dispose()


def test_mfa_routes_are_registered_and_challenge_is_rate_limited():
    from fastapi.testclient import TestClient
    from app.core.platform_security import LoginRateLimiter
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/v1/auth/mfa/status" in paths
    assert "/api/v1/auth/mfa/enroll" in paths
    assert "/api/v1/auth/mfa/confirm" in paths
    assert "/api/v1/auth/mfa/challenge" in paths
    assert "/api/v1/auth/mfa/recovery-codes/rotate" in paths
    assert "/api/v1/auth/mfa/disable" in paths

    original = app.state.public_write_rate_limiter
    app.state.public_write_rate_limiter = LoginRateLimiter(max_attempts=1, window_seconds=300)
    try:
        with TestClient(app) as client:
            first = client.post("/api/v1/auth/mfa/challenge", json={})
            second = client.post("/api/v1/auth/mfa/challenge", json={})
        assert first.status_code == 422
        assert second.status_code == 429
    finally:
        app.state.public_write_rate_limiter = original
