import hashlib
import jwt
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.api.auth_mfa as mfa
from app.api.auth_mfa import MFAChallengeIn, MFAConfirmIn, MFAEnrollIn, MFASensitiveActionIn, mfa_status
from app.api.auth_mfa import _totp_code, complete_mfa_challenge, confirm_mfa_enrollment, disable_mfa, issue_mfa_challenge, start_mfa_enrollment
from app.core.config import settings
from app.core.database import Base
from app.core.models import AuditEvent, MFAChallenge, MFARecoveryCode, PortalAuthorizationCode, User, UserMFAFactor
from app.core.identity_models import UserSession
from app.core.security import current_user, current_user_for_mfa_setup, create_access_token, hash_password
from app.api.routes import login


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, AuditEvent.__table__, MFAChallenge.__table__,
        MFARecoveryCode.__table__, PortalAuthorizationCode.__table__, UserMFAFactor.__table__, UserSession.__table__,
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
        code = _totp_code(mfa._decrypt_secret(factor), fixed_now.timestamp() + 30)
        result = complete_mfa_challenge(MFAChallengeIn(
            challenge_token=login_result["challenge_token"], code=code
        ), db)
        assert result["token_type"] == "bearer"
        assert current_user(token=result["access_token"], db=db).id == user.id
        session = db.query(UserSession).filter_by(user_id=user.id).one()
        assert session.auth_method == "totp"
        assert session.mfa_verified is True
        assert jwt.decode(result["access_token"], settings.secret_key, algorithms=["HS256"])["sid"] == session.id
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
        code = _totp_code(mfa._decrypt_secret(factor), fixed_now.timestamp() + 30)
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
        _, enabled = _enable(db, user)
        factor = db.query(UserMFAFactor).filter_by(user_id=user.id).one()
        login_challenge = issue_mfa_challenge(db, user)
        login_code = _totp_code(mfa._decrypt_secret(factor), fixed_now.timestamp() + 30)
        login_result = complete_mfa_challenge(MFAChallengeIn(
            challenge_token=login_challenge["challenge_token"], code=login_code
        ), db)
        old_access_token = login_result["access_token"]
        tracked_session = db.query(UserSession).filter_by(user_id=user.id).one()
        disable_now = fixed_now + timedelta(seconds=60)
        monkeypatch.setattr(mfa, "_now", lambda: disable_now)
        disable_code = _totp_code(mfa._decrypt_secret(factor), disable_now.timestamp())
        result = disable_mfa(MFASensitiveActionIn(password="correct-password", code=disable_code), user, db)
        db.refresh(user)
        assert result["status"] == "disabled"
        assert user.auth_version == 2
        assert db.query(UserMFAFactor).filter_by(user_id=user.id).count() == 0
        assert db.query(MFARecoveryCode).filter_by(user_id=user.id).filter(
            MFARecoveryCode.revoked_at.is_(None)
        ).count() == 0
        db.refresh(tracked_session)
        assert tracked_session.revoked_at is not None
        assert tracked_session.revoked_reason == "mfa_security_change"
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



def test_privileged_password_login_is_restricted_until_mfa_is_enabled(monkeypatch):
    monkeypatch.setattr(settings, "mfa_encryption_key", mfa.Fernet.generate_key().decode())
    engine = _engine()
    with Session(engine) as db:
        user = _user(db)
        user.platform_role = "root_superadmin"
        db.commit()
        form = OAuth2PasswordRequestForm(username=user.email, password="correct-password", scope="")
        result = login(form, db)
        assert result["mfa_enrollment_required"] is True
        assert result["token_type"] == "bearer"
        with pytest.raises(HTTPException) as blocked:
            current_user(token=result["access_token"], db=db)
        assert blocked.value.status_code == 401
        assert current_user_for_mfa_setup(token=result["access_token"], db=db).id == user.id

        _enable(db, user)
        with pytest.raises(HTTPException) as expired_setup:
            current_user_for_mfa_setup(token=result["access_token"], db=db)
        assert expired_setup.value.status_code == 401
        fresh_token = create_access_token(user.id, user.auth_version, mfa_verified=True)
        assert current_user(token=fresh_token, db=db).id == user.id
    engine.dispose()


@pytest.mark.parametrize("platform_role", [
    "root_superadmin", "platform_admin", "security_admin", "cms_admin",
    "support_admin", "developer_api_admin", "maintenance_admin",
    "incident_commander", "release_manager", "analytics_admin", "recruitment_admin",
])
def test_privileged_role_rejects_legacy_access_token_without_mfa(platform_role):
    engine = _engine()
    with Session(engine) as db:
        user = _user(db)
        user.platform_role = platform_role
        db.commit()
        token = create_access_token(user.id, user.auth_version)
        with pytest.raises(HTTPException) as blocked:
            current_user(token=token, db=db)
        assert blocked.value.status_code == 403
        assert "multi-factor" in blocked.value.detail.lower()
    engine.dispose()



def test_setup_only_token_can_reach_only_mfa_setup_routes(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.core.database import get_db
    from app.main import app

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        User.__table__, AuditEvent.__table__, MFAChallenge.__table__,
        MFARecoveryCode.__table__, PortalAuthorizationCode.__table__, UserMFAFactor.__table__,
    ])
    SessionFactory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False,
    )
    with SessionFactory() as db:
        user = _user(db)
        user.platform_role = "platform_admin"
        db.commit()
        token = create_access_token(user.id, user.auth_version, mfa_setup_only=True)

    def override_db():
        with SessionFactory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            status_response = client.get("/api/v1/auth/mfa/status", headers=headers)
            assert status_response.status_code == 200
            assert status_response.json()["enabled"] is False
            profile_response = client.get("/api/v1/auth/me", headers=headers)
            assert profile_response.status_code == 401
            organizations_response = client.get("/api/v1/organizations", headers=headers)
            assert organizations_response.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine, tables=[
            User.__table__, AuditEvent.__table__, MFAChallenge.__table__,
            MFARecoveryCode.__table__, PortalAuthorizationCode.__table__, UserMFAFactor.__table__,
        ])
        engine.dispose()



def test_mfa_setup_token_expires_within_ten_minutes():
    token = create_access_token(1, 0, mfa_setup_only=True)
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    assert 0 < payload["exp"] - time.time() <= 600


def test_mfa_status_discloses_when_setup_only_token_cannot_manage_sessions():
    engine = _engine()
    with Session(engine) as db:
        user = _user(db)
        db.info["onecore_mfa_setup_only"] = True
        restricted = mfa_status(user=user, db=db)
        assert restricted["session_management_available"] is False
        db.info["onecore_mfa_setup_only"] = False
        normal = mfa_status(user=user, db=db)
        assert normal["session_management_available"] is True
    engine.dispose()
