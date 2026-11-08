import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import Base
from app.core.models import AuditEvent, User
from app.core.security import current_user
from app.api.supabase_auth import SupabaseSessionExchange, exchange_supabase_session


class FakeSupabaseResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__, AuditEvent.__table__])
    return engine


def _identity(email="verified@example.com", **overrides):
    result = {
        "id": str(uuid.uuid4()), "email": email,
        "email_confirmed_at": "2026-11-08T10:00:00Z",
        "is_anonymous": False, "user_metadata": {"full_name": "Verified User"},
    }
    result.update(overrides)
    return result


def _configure_supabase(monkeypatch, identity, status_code=200):
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "test-anon-key")
    monkeypatch.setattr(
        "app.api.supabase_auth.httpx.get",
        lambda *args, **kwargs: FakeSupabaseResponse(status_code, identity),
    )


def test_supabase_auth_session_provisions_onecore_identity_and_issues_api_token(monkeypatch):
    identity = _identity()
    _configure_supabase(monkeypatch, identity)
    engine = _db()
    with Session(engine) as db:
        result = exchange_supabase_session(
            SupabaseSessionExchange(access_token="supabase-access-token-" + "x" * 32), db
        )
        user = db.query(User).filter_by(email=identity["email"]).one()
        assert result["token_type"] == "bearer"
        assert result["access_token"]
        assert user.supabase_auth_user_id == identity["id"]
        assert user.is_active is True
        assert user.full_name == "Verified User"
        assert current_user(result["access_token"], db).id == user.id
    engine.dispose()


def test_supabase_auth_links_verified_email_to_existing_onecore_user(monkeypatch):
    identity = _identity()
    _configure_supabase(monkeypatch, identity)
    engine = _db()
    with Session(engine) as db:
        user = User(email=identity["email"], full_name="Existing User", password_hash="unused")
        db.add(user)
        db.commit()
        original_id = user.id
        exchange_supabase_session(
            SupabaseSessionExchange(access_token="supabase-access-token-" + "x" * 32), db
        )
        assert db.query(User).count() == 1
        assert db.get(User, original_id).supabase_auth_user_id == identity["id"]
    engine.dispose()


def test_supabase_auth_rejects_unverified_or_anonymous_identity(monkeypatch):
    identity = _identity(email_confirmed_at=None)
    _configure_supabase(monkeypatch, identity)
    engine = _db()
    with Session(engine) as db:
        with pytest.raises(HTTPException) as unverified:
            exchange_supabase_session(
                SupabaseSessionExchange(access_token="supabase-access-token-" + "x" * 32), db
            )
        assert unverified.value.status_code == 403
        identity["email_confirmed_at"] = "2026-11-08T10:00:00Z"
        identity["is_anonymous"] = True
        with pytest.raises(HTTPException) as anonymous:
            exchange_supabase_session(
                SupabaseSessionExchange(access_token="supabase-access-token-" + "x" * 32), db
            )
        assert anonymous.value.status_code == 403
        assert db.query(User).count() == 0
    engine.dispose()


def test_supabase_auth_rejects_identity_already_linked_to_another_user(monkeypatch):
    identity = _identity()
    _configure_supabase(monkeypatch, identity)
    engine = _db()
    with Session(engine) as db:
        other = User(
            email="other@example.com", full_name="Other", password_hash="unused",
            supabase_auth_user_id=identity["id"],
        )
        existing = User(email=identity["email"], full_name="Existing", password_hash="unused")
        db.add_all([other, existing])
        db.commit()
        with pytest.raises(HTTPException) as denied:
            exchange_supabase_session(
                SupabaseSessionExchange(access_token="supabase-access-token-" + "x" * 32), db
            )
        assert denied.value.status_code == 409
    engine.dispose()


def test_supabase_auth_exchange_is_disabled_without_project_credentials(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_anon_key", "")
    engine = _db()
    with Session(engine) as db:
        with pytest.raises(HTTPException) as disabled:
            exchange_supabase_session(
                SupabaseSessionExchange(access_token="supabase-access-token-" + "x" * 32), db
            )
        assert disabled.value.status_code == 503
    engine.dispose()


def test_supabase_auth_identity_migration_is_chained_after_developer_keys():
    from pathlib import Path

    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0057_supabase_auth_identity.py"
    source = migration.read_text()
    assert 'revision = "0057_supabase_auth_identity"' in source
    assert 'down_revision = "0056_developer_api_keys"' in source
    assert "supabase_auth_user_id" in source


def test_supabase_auth_exchange_route_is_registered():
    from app.main import app

    assert "/api/v1/auth/supabase-session" in app.openapi()["paths"]
