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


def test_verified_supabase_access_token_links_existing_onecore_account(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "test-supabase-secret-at-least-32-bytes")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__])
    with Session(engine) as db:
        user = User(email="member@example.com", full_name="Member", password_hash="unused")
        db.add(user)
        db.commit()
        subject = "7c5a9c4c-2d39-4b1d-9d8f-5a2a3d2b1c00"
        token = jwt.encode({
            "sub": subject, "email": "member@example.com", "email_verified": True,
            "role": "authenticated", "aud": "authenticated",
            "iss": "https://project.supabase.co/auth/v1", "exp": int(time.time()) + 300,
        }, settings.supabase_jwt_secret, algorithm="HS256")
        resolved = current_user(token, db)
        assert resolved.id == user.id
        assert resolved.supabase_auth_user_id == subject
        assert current_user(token, db).id == user.id
    engine.dispose()


def test_supabase_auth_rejects_unverified_email(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "test-supabase-secret-at-least-32-bytes")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__])
    with Session(engine) as db:
        token = jwt.encode({
            "sub": "7c5a9c4c-2d39-4b1d-9d8f-5a2a3d2b1c00", "email": "member@example.com",
            "email_verified": False, "role": "authenticated", "aud": "authenticated",
            "iss": "https://project.supabase.co/auth/v1", "exp": int(time.time()) + 300,
        }, settings.supabase_jwt_secret, algorithm="HS256")
        with pytest.raises(HTTPException) as denied:
            current_user(token, db)
        assert denied.value.status_code == 401
    engine.dispose()
