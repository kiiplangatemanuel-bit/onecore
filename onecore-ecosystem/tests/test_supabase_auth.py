import time
import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import Base
from app.core.models import User
from app.core.security import current_user


def _token(secret, email="member@example.com", verified=True):
    return jwt.encode({
        "sub": "7c5a9c4c-2d39-4b1d-9d8f-5a2a3d2b1c00", "email": email,
        "email_verified": verified, "user_metadata": {"full_name": "Member"},
        "role": "authenticated", "aud": "authenticated",
        "iss": "https://project.supabase.co/auth/v1", "exp": int(time.time()) + 300,
    }, secret, algorithm="HS256")


def test_verified_supabase_identity_is_linked_to_existing_onecore_account(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "test-supabase-secret-at-least-32-bytes")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__])
    with Session(engine) as db:
        user = User(email="member@example.com", full_name="Member", password_hash="unused")
        db.add(user); db.commit()
        resolved = current_user(_token(settings.supabase_jwt_secret), db)
        assert resolved.id == user.id
        assert resolved.supabase_auth_user_id == "7c5a9c4c-2d39-4b1d-9d8f-5a2a3d2b1c00"
        assert current_user(_token(settings.supabase_jwt_secret), db).id == user.id
    engine.dispose()


def test_verified_supabase_identity_can_provision_unassigned_onecore_user(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "test-supabase-secret-at-least-32-bytes")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__])
    with Session(engine) as db:
        user = current_user(_token(settings.supabase_jwt_secret, email="new@example.com"), db)
        assert user.email == "new@example.com"
        assert user.is_active is True
        assert user.supabase_auth_user_id
    engine.dispose()


def test_supabase_auth_rejects_unverified_email(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "test-supabase-secret-at-least-32-bytes")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__])
    with Session(engine) as db:
        with pytest.raises(HTTPException) as denied:
            current_user(_token(settings.supabase_jwt_secret, verified=False), db)
        assert denied.value.status_code == 401
    engine.dispose()
