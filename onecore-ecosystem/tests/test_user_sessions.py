from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.user_sessions import (
    list_user_sessions,
    revoke_other_sessions,
    revoke_user_session,
)
from app.core.database import Base
from app.core.identity_models import UserSession
from app.core.models import AuditEvent, User
from app.core.security import create_access_token, current_user


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, AuditEvent.__table__, UserSession.__table__,
    ])
    return engine


def _user(db, email):
    user = User(email=email, full_name=email.split("@")[0], password_hash="unused")
    db.add(user)
    db.flush()
    return user


def _session(user, *, expires_at=None, revoked_at=None, mfa_verified=False):
    now = datetime.now(timezone.utc)
    return UserSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        auth_version=int(user.auth_version or 0),
        auth_method="password",
        mfa_verified=mfa_verified,
        device_name="Office laptop",
        user_agent="OneCore test client",
        created_at=now,
        last_seen_at=now,
        expires_at=expires_at or now + timedelta(hours=1),
        revoked_at=revoked_at,
        revoked_reason="",
    )


def test_session_inventory_is_account_scoped_and_marks_current_device():
    engine = _database()
    with Session(engine) as db:
        first = _user(db, "first@example.com")
        second = _user(db, "second@example.com")
        current = _session(first)
        other = _session(first)
        private = _session(second)
        db.add_all([current, other, private])
        db.commit()
        db.info["onecore_session_id"] = current.id

        result = list_user_sessions(user=first, db=db)

        assert {item["id"] for item in result["sessions"]} == {current.id, other.id}
        assert next(item for item in result["sessions"] if item["id"] == current.id)["current"] is True
        assert all(item["id"] != private.id for item in result["sessions"])
        assert result["legacy_session"] is False
    engine.dispose()


def test_account_can_revoke_own_session_but_cannot_discover_or_revoke_another_users():
    engine = _database()
    with Session(engine) as db:
        owner = _user(db, "owner@example.com")
        stranger = _user(db, "stranger@example.com")
        owned = _session(owner)
        foreign = _session(stranger)
        db.add_all([owned, foreign])
        db.commit()
        db.info["onecore_session_id"] = owned.id

        result = revoke_user_session(session_id=owned.id, user=owner, db=db)
        assert result == {"status": "revoked", "current_session": True}
        assert db.get(UserSession, owned.id).revoked_reason == "user_revoked_session"

        with pytest.raises(HTTPException) as denied:
            revoke_user_session(session_id=foreign.id, user=owner, db=db)
        assert denied.value.status_code == 404
        assert db.get(UserSession, foreign.id).revoked_at is None
        events = db.query(AuditEvent).filter_by(action="auth.session.revoked").all()
        assert len(events) == 1
        assert events[0].resource_id == owned.id
    engine.dispose()


def test_revoke_others_preserves_current_and_only_revokes_other_live_sessions():
    engine = _database()
    with Session(engine) as db:
        owner = _user(db, "owner@example.com")
        now = datetime.now(timezone.utc)
        current = _session(owner)
        other = _session(owner)
        expired = _session(owner, expires_at=now - timedelta(minutes=1))
        already_revoked = _session(owner, revoked_at=now - timedelta(minutes=2))
        already_revoked.revoked_reason = "previous_action"
        db.add_all([current, other, expired, already_revoked])
        db.commit()
        db.info["onecore_session_id"] = current.id

        result = revoke_other_sessions(user=owner, db=db)

        assert result["revoked_count"] == 1
        assert result["current_session_id"] == current.id
        assert db.get(UserSession, current.id).revoked_at is None
        assert db.get(UserSession, other.id).revoked_reason == "user_revoked_other_sessions"
        assert db.get(UserSession, expired.id).revoked_at is None
        assert db.get(UserSession, already_revoked.id).revoked_reason == "previous_action"
        assert db.query(AuditEvent).filter_by(
            action="auth.sessions.other_sessions_revoked"
        ).count() == 1
    engine.dispose()


def test_revoke_others_requires_a_tracked_current_session():
    engine = _database()
    with Session(engine) as db:
        user = _user(db, "legacy@example.com")
        with pytest.raises(HTTPException) as denied:
            revoke_other_sessions(user=user, db=db)
        assert denied.value.status_code == 409
    engine.dispose()


def test_revoked_tracked_session_invalidates_a_still_signed_bearer_token():
    engine = _database()
    with Session(engine) as db:
        user = _user(db, "session@example.com")
        row = _session(user)
        db.add(row)
        db.commit()
        token = create_access_token(
            user.id, user.auth_version, session_id=row.id, expires_at=row.expires_at
        )
        assert current_user(token=token, db=db).id == user.id

        row.revoked_at = datetime.now(timezone.utc)
        row.revoked_reason = "test_revocation"
        db.commit()
        with pytest.raises(HTTPException) as denied:
            current_user(token=token, db=db)
        assert denied.value.status_code == 401
    engine.dispose()


def test_session_expiry_is_checked_against_database_even_if_jwt_is_still_valid():
    engine = _database()
    with Session(engine) as db:
        user = _user(db, "expired@example.com")
        row = _session(user, expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        db.add(row)
        db.commit()
        token = create_access_token(
            user.id, user.auth_version, session_id=row.id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=20),
        )
        with pytest.raises(HTTPException) as denied:
            current_user(token=token, db=db)
        assert denied.value.status_code == 401
    engine.dispose()


def test_tracked_token_mfa_assurance_must_match_durable_session_record():
    engine = _database()
    with Session(engine) as db:
        user = _user(db, "assurance@example.com")
        row = _session(user, mfa_verified=False)
        db.add(row)
        db.commit()
        token = create_access_token(
            user.id, user.auth_version, mfa_verified=True,
            session_id=row.id, expires_at=row.expires_at,
        )
        with pytest.raises(HTTPException) as denied:
            current_user(token=token, db=db)
        assert denied.value.status_code == 401
    engine.dispose()


def test_identity_session_migration_uses_account_owner_only_forced_rls():
    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0064_identity_sessions.py"
    source = migration.read_text()
    assert 'revision = "0064_identity_sessions"' in source
    assert 'down_revision = "0063_fx_statutory_remittances"' in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "user_id = NULLIF(current_setting('app.user_id', true), '')::integer" in source
    assert "onecore_is_platform_admin" not in source


def test_session_routes_are_registered():
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/v1/auth/sessions" in paths
    assert "/api/v1/auth/sessions/revoke-others" in paths
    assert "/api/v1/auth/sessions/{session_id}" in paths
