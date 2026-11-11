import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote
from cryptography.fernet import Fernet
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.api.auth_workflows as workflows
from app.api.auth_workflows import confirm_password_reset, request_password_reset
from app.core.database import Base
from app.core.models import AuditEvent, PasswordResetToken, PortalAuthorizationCode, User
from app.core.identity_models import IdentityEmailDelivery, UserSession
from app.core.schemas import PasswordResetConfirmIn, PasswordResetRequestIn
from app.core.security import create_access_token, current_user, verify_password
from app.services.identity_email import decrypt_identity_email_payload


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, PasswordResetToken.__table__, PortalAuthorizationCode.__table__, UserSession.__table__, IdentityEmailDelivery.__table__, AuditEvent.__table__,
    ])
    return engine


def test_password_reset_request_is_non_enumerating_and_stores_only_token_hash(monkeypatch):
    monkeypatch.setattr(workflows.settings, "identity_email_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(workflows.settings, "integration_email_enabled", True)
    monkeypatch.setattr(workflows.settings, "email_host", "smtp.example.test")
    monkeypatch.setattr(workflows.settings, "email_from", "no-reply@example.test")
    monkeypatch.setattr(workflows.settings, "public_site_url", "https://onecore.example.test")
    engine = _engine()
    with Session(engine) as db:
        user = User(email="member@example.com", full_name="Member", password_hash="old-hash", is_active=True)
        db.add(user)
        db.commit()

        known = request_password_reset(PasswordResetRequestIn(email="MEMBER@example.com"), db)
        unknown = request_password_reset(PasswordResetRequestIn(email="missing@example.com"), db)

        assert known == unknown
        assert known["status"] == "accepted"
        assert "token" not in known
        row = db.query(PasswordResetToken).filter_by(user_id=user.id).one()
        delivery = db.query(IdentityEmailDelivery).filter_by(
            user_id=user.id, purpose="password_reset"
        ).one()
        encrypted_payload = decrypt_identity_email_payload(delivery)
        reset_url = next(
            line for line in encrypted_payload["body"].splitlines()
            if "/reset-password#token=" in line
        )
        raw_token = unquote(reset_url.split("#token=", 1)[1])
        assert row.token_hash == hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        assert raw_token not in delivery.payload_ciphertext
        assert row.expires_at is not None
        assert encrypted_payload["recipient_email"] == user.email
    engine.dispose()


def test_password_reset_queue_failure_rolls_back_token_without_account_disclosure(monkeypatch):
    monkeypatch.setattr(workflows.settings, "identity_email_encryption_key", "")
    monkeypatch.setattr(workflows.settings, "integration_email_enabled", True)
    monkeypatch.setattr(workflows.settings, "email_host", "smtp.example.test")
    monkeypatch.setattr(workflows.settings, "email_from", "no-reply@example.test")
    monkeypatch.setattr(workflows.settings, "public_site_url", "https://onecore.example.test")
    engine = _engine()
    with Session(engine) as db:
        user = User(email="member@example.com", full_name="Member", password_hash="old-hash", is_active=True)
        db.add(user)
        db.commit()
        response = request_password_reset(PasswordResetRequestIn(email="member@example.com"), db)
        assert response["status"] == "accepted"
        assert db.query(PasswordResetToken).count() == 0
        assert db.query(IdentityEmailDelivery).count() == 0
        assert db.query(AuditEvent).count() == 0
    engine.dispose()


def test_password_reset_consumes_token_and_invalidates_existing_access_tokens():
    engine = _engine()
    with Session(engine) as db:
        user = User(email="member@example.com", full_name="Member", password_hash="old-hash", is_active=True)
        db.add(user)
        db.commit()
        old_token = create_access_token(user.id, user.auth_version)
        now = datetime.now(timezone.utc)
        tracked_session = UserSession(
            id=str(uuid.uuid4()), user_id=user.id, auth_version=user.auth_version,
            auth_method="password", mfa_verified=False, device_name="Test device",
            user_agent="Test client", created_at=now, last_seen_at=now,
            expires_at=now + timedelta(hours=1),
        )
        db.add(tracked_session)
        raw = "r" * 48
        row = PasswordResetToken(
            user_id=user.id,
            token_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        db.add(row)
        pending_delivery = IdentityEmailDelivery(
            user_id=user.id,
            purpose="password_reset",
            event_key="password-reset:pending",
            payload_ciphertext="encrypted-payload",
            status="pending",
            attempts=0,
            next_attempt_at=now,
            expires_at=now + timedelta(minutes=30),
        )
        db.add(pending_delivery)
        portal_code = PortalAuthorizationCode(
            code_hash=hashlib.sha256(b"one-time-portal-code").hexdigest(),
            user_id=user.id,
            redirect_uri="https://support.example.com/callback",
            code_challenge="c" * 43,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=90),
        )
        db.add(portal_code)
        db.commit()

        result = confirm_password_reset(
            PasswordResetConfirmIn(token=raw, new_password="a-new-secure-password"),
            db,
        )
        db.refresh(user)
        db.refresh(row)
        db.refresh(portal_code)
        db.refresh(tracked_session)
        assert result["status"] == "password_reset"
        assert tracked_session.revoked_at is not None
        assert tracked_session.revoked_reason == "password_reset"
        assert row.consumed_at is not None
        db.refresh(pending_delivery)
        assert pending_delivery.status == "cancelled"
        assert portal_code.consumed_at is not None
        assert user.auth_version == 1
        assert verify_password("a-new-secure-password", user.password_hash)
        with pytest.raises(HTTPException) as revoked:
            current_user(token=old_token, db=db)
        assert revoked.value.status_code == 401
        new_token = create_access_token(user.id, user.auth_version)
        assert current_user(token=new_token, db=db).id == user.id
        with pytest.raises(HTTPException) as replay:
            confirm_password_reset(
                PasswordResetConfirmIn(token=raw, new_password="another-secure-password"),
                db,
            )
        assert replay.value.status_code == 400
    engine.dispose()


def test_password_reset_rejects_expired_tokens():
    engine = _engine()
    with Session(engine) as db:
        user = User(email="member@example.com", full_name="Member", password_hash="old-hash", is_active=True)
        db.add(user)
        db.commit()
        raw = "e" * 48
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        ))
        db.commit()
        with pytest.raises(HTTPException) as expired:
            confirm_password_reset(
                PasswordResetConfirmIn(token=raw, new_password="a-new-secure-password"),
                db,
            )
        assert expired.value.status_code == 400
    engine.dispose()


def test_password_reset_routes_are_registered():
    from app.main import app
    paths = set(app.openapi()["paths"])
    assert "/api/v1/auth/password-reset/request" in paths
    assert "/api/v1/auth/password-reset/confirm" in paths


@pytest.mark.parametrize(
    "path",
    ["/api/v1/auth/password-reset/request", "/api/v1/auth/password-reset/confirm"],
)
def test_password_reset_public_routes_are_rate_limited(path):
    from fastapi.testclient import TestClient
    from app.core.platform_security import LoginRateLimiter
    from app.main import app

    original = app.state.public_write_rate_limiter
    app.state.public_write_rate_limiter = LoginRateLimiter(max_attempts=1, window_seconds=300)
    try:
        with TestClient(app) as client:
            first = client.post(path, json={})
            second = client.post(path, json={})
        assert first.status_code == 422
        assert second.status_code == 429
        assert second.headers["retry-after"] == "300"
    finally:
        app.state.public_write_rate_limiter = original
