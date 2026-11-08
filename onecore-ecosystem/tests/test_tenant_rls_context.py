import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request
from types import SimpleNamespace


def test_verified_organization_context_is_positive_and_persists_for_new_transactions():
    from app.core.security import set_verified_organization_context

    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as db:
        set_verified_organization_context(db, 42)
        assert db.info["onecore_organization_id"] == 42
        with pytest.raises(ValueError):
            set_verified_organization_context(db, 0)
    engine.dispose()


def test_active_membership_binds_rls_context_only_after_membership_verification(monkeypatch):
    from app.core import tenancy
    from app.core.models import Membership, Organization

    membership = SimpleNamespace(user_id=7, organization_id=42, is_active=True)
    organization = SimpleNamespace(id=42, is_active=True)

    class Query:
        def filter_by(self, **kwargs):
            assert kwargs == {"user_id": 7, "organization_id": 42, "is_active": True}
            return self

        def first(self):
            return membership

    class Database:
        def query(self, model):
            assert model is Membership
            return Query()

        def get(self, model, identity):
            assert model is Organization
            assert identity == 42
            return organization

    bound = []
    monkeypatch.setattr(tenancy, "organization_for_host", lambda db, host: None)
    monkeypatch.setattr(tenancy, "set_verified_organization_context", lambda db, org_id: bound.append(org_id))
    request = Request({
        "type": "http", "method": "GET", "path": "/", "headers": [],
        "query_string": b"", "server": ("onecore.co.ke", 80), "scheme": "https",
        "client": ("127.0.0.1", 1234), "root_path": "",
    })

    result = tenancy.active_membership(request, 42, SimpleNamespace(id=7), Database())

    assert result is membership
    assert bound == [42]


def test_active_membership_does_not_bind_rls_context_for_inactive_membership(monkeypatch):
    from app.core import tenancy
    from app.core.models import Membership, Organization

    class Query:
        def filter_by(self, **kwargs):
            return self

        def first(self):
            return None

    class Database:
        def query(self, model):
            assert model is Membership
            return Query()

        def get(self, model, identity):
            assert model is Organization
            return SimpleNamespace(id=42, is_active=True)

    bound = []
    monkeypatch.setattr(tenancy, "organization_for_host", lambda db, host: None)
    monkeypatch.setattr(tenancy, "set_verified_organization_context", lambda db, org_id: bound.append(org_id))
    request = Request({
        "type": "http", "method": "GET", "path": "/", "headers": [],
        "query_string": b"", "server": ("onecore.co.ke", 80), "scheme": "https",
        "client": ("127.0.0.1", 1234), "root_path": "",
    })

    with pytest.raises(HTTPException) as error:
        tenancy.active_membership(request, 42, SimpleNamespace(id=7), Database())

    assert error.value.status_code == 403
    assert bound == []


def test_provider_callback_context_does_not_store_raw_callback_secrets():
    from app.core.security import set_provider_callback_token_context

    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as db:
        set_provider_callback_token_context(db, "a" * 64)
        assert "onecore_user_id" not in db.info
        assert "onecore_organization_id" not in db.info
    engine.dispose()
