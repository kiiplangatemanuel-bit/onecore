import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.api.auth_workflows as workflows
from app.api.auth_workflows import confirm_password_reset, request_password_reset
from app.core.database import Base
from app.core.models import AuditEvent, PasswordResetToken, PortalAuthorizationCode, User
from app.core.schemas import PasswordResetConfirmIn, PasswordResetRequestIn
from app.core.security import create_access_token, current_user, verify_password


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, PasswordResetToken.__table__, PortalAuthorizationCode.__table__, AuditEvent.__table__,
    ])
    return engine


def test_password_reset_request_is_non_enumerating_and_stores_only_token_hash(monkeypatch):
    sent = {}
    monkeypatch.setattr(
        workflows,
        "_send_password_reset_email",
        lambda email, full_name, token: sent.update(email=email, full_name=full_name, token=token),
    )
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
        assert row.token_hash == hashlib.sha256(sent["token"].encode("utf-8")).hexdigest()
        assert row.token_hash != sent["token"]
        assert row.expires_at is not None
        assert sent["email"] == user.email
    engine.dispose()


def test_password_reset_delivery_failure_rolls_back_token_without_account_disclosure(monkeypatch):
    def fail_delivery(*_args):
        raise RuntimeError("SMTP unavailable")

    monkeypatch.setattr(workflows, "_send_password_reset_email", fail_delivery)
    engine = _engine()
    with Session(engine) as db:
        user = User(email="member@example.com", full_name="Member", password_hash="old-hash", is_active=True)
        db.add(user)
        db.commit()
        response = request_password_reset(PasswordResetRequestIn(email="member@example.com"), db)
        assert response["status"] == "accepted"
        assert db.query(PasswordResetToken).count() == 0
        assert db.query(AuditEvent).count() == 0
    engine.dispose()


def test_password_reset_consumes_token_and_invalidates_existing_access_tokens():
    engine = _engine()
    with Session(engine) as db:
        user = User(email="member@example.com", full_name="Member", password_hash="old-hash", is_active=True)
        db.add(user)
        db.commit()
        old_token = create_access_token(user.id, user.auth_version)
        raw = "r" * 48
        row = PasswordResetToken(
            user_id=user.id,
            token_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        db.add(row)
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
        assert result["status"] == "password_reset"
        assert row.consumed_at is not None
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
