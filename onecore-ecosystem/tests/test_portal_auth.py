import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import Base
from app.core.models import AuditEvent, PortalAuthorizationCode, User
from app.core.identity_models import PortalAuthorizationAssurance, UserSession
from app.api.portal_auth import PortalCodeExchange, PortalCodeRequest, exchange_portal_code, issue_portal_code


def _pkce_pair():
    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def test_portal_code_is_origin_bound_pkce_protected_and_single_use(monkeypatch):
    monkeypatch.setattr(settings, "portal_redirect_origins", "https://support.example.com")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, PortalAuthorizationCode.__table__, AuditEvent.__table__,
        PortalAuthorizationAssurance.__table__, UserSession.__table__,
    ])
    verifier, challenge = _pkce_pair()
    redirect_uri = "https://support.example.com/tickets"
    with Session(engine) as db:
        user = User(email="member@example.com", full_name="Member", password_hash="unused")
        db.add(user)
        db.commit()
        issued = issue_portal_code(
            PortalCodeRequest(redirect_uri=redirect_uri, state="s" * 32, code_challenge=challenge),
            user, db,
        )
        query = parse_qs(urlsplit(issued["redirect_url"]).query)
        code = query["code"][0]
        assert query["state"] == ["s" * 32]
        assert code not in db.query(PortalAuthorizationCode).one().code_hash

        with pytest.raises(HTTPException) as wrong_pkce:
            exchange_portal_code(PortalCodeExchange(
                code=code, redirect_uri=redirect_uri, code_verifier="x" * 64,
            ), db)
        assert wrong_pkce.value.status_code == 400

        exchanged = exchange_portal_code(PortalCodeExchange(
            code=code, redirect_uri=redirect_uri, code_verifier=verifier,
        ), db)
        assert exchanged["token_type"] == "bearer"
        assert exchanged["access_token"]
        session = db.query(UserSession).one()
        assert session.auth_method == "portal"
        assert session.mfa_verified is False
        with pytest.raises(HTTPException) as replay:
            exchange_portal_code(PortalCodeExchange(
                code=code, redirect_uri=redirect_uri, code_verifier=verifier,
            ), db)
        assert replay.value.status_code == 400
    engine.dispose()


def test_portal_code_rejects_unregistered_redirect_origin(monkeypatch):
    monkeypatch.setattr(settings, "portal_redirect_origins", "https://docs.example.com")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, PortalAuthorizationCode.__table__, AuditEvent.__table__,
    ])
    with Session(engine) as db:
        user = User(email="member@example.com", full_name="Member", password_hash="unused")
        db.add(user)
        db.commit()
        verifier, challenge = _pkce_pair()
        with pytest.raises(HTTPException) as denied:
            issue_portal_code(
                PortalCodeRequest(
                    redirect_uri="https://evil.example.net/callback",
                    state="s" * 32,
                    code_challenge=challenge,
                ), user, db,
            )
        assert denied.value.status_code == 400
        assert db.query(PortalAuthorizationCode).count() == 0
    engine.dispose()


def test_portal_auth_routes_are_registered():
    from app.main import app
    paths = set(app.openapi()["paths"])
    assert "/api/v1/auth/portal-code" in paths
    assert "/api/v1/auth/exchange-portal-code" in paths



def test_privileged_portal_handoff_preserves_verified_mfa_assurance(monkeypatch):
    monkeypatch.setattr(settings, "portal_redirect_origins", "https://admin.example.com")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, PortalAuthorizationCode.__table__, AuditEvent.__table__,
        PortalAuthorizationAssurance.__table__, UserSession.__table__,
    ])
    verifier, challenge = _pkce_pair()
    redirect_uri = "https://admin.example.com/security"
    with Session(engine) as db:
        user = User(
            email="admin@example.com", full_name="Platform Admin",
            password_hash="unused", platform_role="root_superadmin",
        )
        db.add(user)
        db.commit()
        db.info["onecore_mfa_verified"] = True
        issued = issue_portal_code(
            PortalCodeRequest(redirect_uri=redirect_uri, state="a" * 32, code_challenge=challenge),
            user, db,
        )
        assert db.query(PortalAuthorizationAssurance).one().mfa_verified is True
        code = parse_qs(urlsplit(issued["redirect_url"]).query)["code"][0]
        exchanged = exchange_portal_code(
            PortalCodeExchange(code=code, redirect_uri=redirect_uri, code_verifier=verifier), db
        )
        session = db.query(UserSession).filter_by(user_id=user.id).one()
        assert session.mfa_verified is True
        assert session.auth_method == "portal"
        assert exchanged["access_token"]
    engine.dispose()


def test_privileged_portal_handoff_without_mfa_assurance_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "portal_redirect_origins", "https://admin.example.com")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, PortalAuthorizationCode.__table__, AuditEvent.__table__,
        PortalAuthorizationAssurance.__table__, UserSession.__table__,
    ])
    verifier, challenge = _pkce_pair()
    redirect_uri = "https://admin.example.com/security"
    with Session(engine) as db:
        user = User(
            email="admin@example.com", full_name="Platform Admin",
            password_hash="unused", platform_role="root_superadmin",
        )
        db.add(user)
        db.commit()
        db.info["onecore_mfa_verified"] = False
        issued = issue_portal_code(
            PortalCodeRequest(redirect_uri=redirect_uri, state="b" * 32, code_challenge=challenge),
            user, db,
        )
        code = parse_qs(urlsplit(issued["redirect_url"]).query)["code"][0]
        with pytest.raises(HTTPException) as denied:
            exchange_portal_code(
                PortalCodeExchange(code=code, redirect_uri=redirect_uri, code_verifier=verifier), db
            )
        assert denied.value.status_code == 403
        assert db.query(UserSession).filter_by(user_id=user.id).count() == 0
    engine.dispose()
