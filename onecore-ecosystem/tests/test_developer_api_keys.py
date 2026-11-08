from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fastapi import HTTPException
from starlette.requests import Request
import pytest

from app.core.database import Base
from app.core.models import (
    AuditEvent, DeveloperApiKey, DeveloperApiKeyUsage, Membership, Organization, User,
)
from app.api.developer_api_keys import (
    DeveloperApiKeyCreate, create_developer_api_key, list_developer_api_keys,
    revoke_developer_api_key, current_developer_api_key, developer_api_organization,
)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, Organization.__table__, Membership.__table__,
        AuditEvent.__table__, DeveloperApiKey.__table__, DeveloperApiKeyUsage.__table__,
    ])
    return engine


def _user(db, organization, email, role="developer"):
    user = User(email=email, full_name=email.split("@")[0], password_hash="unused")
    db.add(user)
    db.flush()
    db.add(Membership(
        user_id=user.id, organization_id=organization.id,
        role=role, is_active=True,
    ))
    db.flush()
    return user


def test_developer_api_key_is_issued_once_hashed_and_scoped_to_active_organization():
    engine = _db()
    with Session(engine) as db:
        org = Organization(name="Tenant A", slug="tenant-a")
        db.add(org)
        db.flush()
        developer = _user(db, org, "dev@example.com")
        db.commit()

        created = create_developer_api_key(
            DeveloperApiKeyCreate(
                organization_id=org.id, name="Integration test",
                environment="sandbox", scopes=["organization:read"],
            ), developer, db,
        )
        assert created["secret"].startswith("oc_test_")
        assert len(created["secret"]) >= 40
        key = db.query(DeveloperApiKey).filter_by(id=created["id"]).one()
        assert key.secret_hash != created["secret"]
        assert key.secret_hash
        listed = list_developer_api_keys(org.id, developer, db)
        assert len(listed) == 1
        assert "secret" not in listed[0]
        assert listed[0]["key_prefix"] == created["key_prefix"]
    engine.dispose()


def test_developer_api_key_management_requires_active_developer_or_org_admin_membership():
    engine = _db()
    with Session(engine) as db:
        org = Organization(name="Tenant A", slug="tenant-a")
        db.add(org)
        db.flush()
        staff = _user(db, org, "staff@example.com", role="staff")
        db.commit()
        with pytest.raises(HTTPException) as denied:
            create_developer_api_key(
                DeveloperApiKeyCreate(organization_id=org.id, name="Not allowed"),
                staff, db,
            )
        assert denied.value.status_code == 404
    engine.dispose()


def test_developer_api_key_authentication_records_usage_and_rejects_revoked_keys():
    engine = _db()
    with Session(engine) as db:
        org = Organization(name="Tenant A", slug="tenant-a")
        db.add(org)
        db.flush()
        developer = _user(db, org, "dev@example.com")
        db.commit()
        created = create_developer_api_key(
            DeveloperApiKeyCreate(organization_id=org.id, name="Usage test"),
            developer, db,
        )
        request = Request({
            "type": "http", "method": "GET", "path": "/api/v1/developer/v1/organization",
            "headers": [], "query_string": b"", "scheme": "https",
            "server": ("api.example.com", 443), "client": ("127.0.0.1", 1234),
        })
        key = current_developer_api_key(request, created["secret"], db)
        response = developer_api_organization(request, key, db)
        assert response["organization"]["id"] == org.id
        assert db.query(DeveloperApiKeyUsage).filter_by(api_key_id=key.id).count() == 1
        revoked = revoke_developer_api_key(key.id, developer, db)
        assert revoked["revoked"] is True
        with pytest.raises(HTTPException) as denied:
            current_developer_api_key(request, created["secret"], db)
        assert denied.value.status_code == 401
    engine.dispose()


def test_developer_api_key_rejects_unsupported_scopes():
    engine = _db()
    with Session(engine) as db:
        org = Organization(name="Tenant A", slug="tenant-a")
        db.add(org)
        db.flush()
        developer = _user(db, org, "dev@example.com")
        db.commit()
        with pytest.raises(HTTPException) as denied:
            create_developer_api_key(
                DeveloperApiKeyCreate(
                    organization_id=org.id, name="Bad scope",
                    scopes=["admin:root"],
                ), developer, db,
            )
        assert denied.value.status_code == 422
    engine.dispose()


def test_developer_api_key_migration_is_chained_after_support_attachments():
    from pathlib import Path

    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0056_developer_api_keys.py"
    source = migration.read_text()
    assert 'revision = "0056_developer_api_keys"' in source
    assert 'down_revision = "0055_support_attachments"' in source
    assert "developer_api_key_select" in source
    assert "developer_api_key_usage_insert" in source


def test_developer_api_key_routes_are_registered():
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/v1/developer/api-keys" in paths
    assert "/api/v1/developer/api-keys/{key_id}/revoke" in paths
    assert "/api/v1/developer/api-keys/{key_id}/usage" in paths
    assert "/api/v1/developer/v1/organization" in paths


def test_developer_api_key_cannot_be_managed_by_another_tenant():
    engine = _db()
    with Session(engine) as db:
        org_a = Organization(name="A", slug="org-a")
        org_b = Organization(name="B", slug="org-b")
        db.add_all([org_a, org_b])
        db.flush()
        owner = _user(db, org_a, "owner@example.com")
        outsider = _user(db, org_b, "outsider@example.com", role="org_admin")
        db.commit()
        created = create_developer_api_key(
            DeveloperApiKeyCreate(organization_id=org_a.id, name="Tenant A key"),
            owner, db,
        )
        with pytest.raises(HTTPException) as denied:
            revoke_developer_api_key(created["id"], outsider, db)
        assert denied.value.status_code == 404
        assert db.query(DeveloperApiKey).filter_by(id=created["id"]).one().revoked_at is None
    engine.dispose()


def test_developer_api_key_stops_working_when_issuing_user_is_deactivated():
    engine = _db()
    with Session(engine) as db:
        org = Organization(name="Tenant A", slug="tenant-a")
        db.add(org)
        db.flush()
        developer = _user(db, org, "dev@example.com")
        db.commit()
        created = create_developer_api_key(
            DeveloperApiKeyCreate(organization_id=org.id, name="Deactivation test"),
            developer, db,
        )
        developer.is_active = False
        db.commit()
        request = Request({
            "type": "http", "method": "GET", "path": "/api/v1/developer/v1/organization",
            "headers": [], "query_string": b"", "scheme": "https",
            "server": ("api.example.com", 443), "client": ("127.0.0.1", 1234),
        })
        with pytest.raises(HTTPException) as denied:
            current_developer_api_key(request, created["secret"], db)
        assert denied.value.status_code == 401
    engine.dispose()



def _api_request():
    return Request({
        "type": "http", "method": "GET", "path": "/api/v1/developer/v1/organization",
        "headers": [], "query_string": b"", "scheme": "https",
        "server": ("api.example.com", 443), "client": ("127.0.0.1", 1234),
    })


def test_sandbox_api_key_reads_only_synthetic_organization_data():
    engine = _db()
    with Session(engine) as db:
        org = Organization(
            name="CONFIDENTIAL Production Tenant", slug="private-production-tenant",
            industry="healthcare", country="KE", currency="KES",
        )
        db.add(org)
        db.flush()
        developer = _user(db, org, "sandbox-dev@example.com")
        db.commit()
        created = create_developer_api_key(
            DeveloperApiKeyCreate(
                organization_id=org.id, name="Sandbox integration",
                environment="sandbox", scopes=["organization:read"],
            ), developer, db,
        )
        request = _api_request()
        key = current_developer_api_key(request, created["secret"], db)
        response = developer_api_organization(request, key, db)
        assert response["organization"]["id"] == "sandbox-organization"
        assert response["organization"]["name"] == "OneCore Sandbox Organization"
        assert response["organization"]["slug"] == "onecore-sandbox"
        assert "CONFIDENTIAL" not in str(response)
        assert response["api_key"]["data_mode"] == "synthetic"
    engine.dispose()


def test_production_api_key_reads_only_its_authorized_organization():
    engine = _db()
    with Session(engine) as db:
        org = Organization(
            name="Production Tenant", slug="production-tenant",
            industry="retail", country="KE", currency="KES",
        )
        db.add(org)
        db.flush()
        developer = _user(db, org, "production-admin@example.com", role="org_admin")
        db.commit()
        created = create_developer_api_key(
            DeveloperApiKeyCreate(
                organization_id=org.id, name="Production integration",
                environment="production", scopes=["organization:read"],
            ), developer, db,
        )
        request = _api_request()
        key = current_developer_api_key(request, created["secret"], db)
        response = developer_api_organization(request, key, db)
        assert response["organization"]["id"] == org.id
        assert response["organization"]["name"] == "Production Tenant"
        assert response["api_key"]["data_mode"] == "live"
    engine.dispose()


def test_developer_role_cannot_issue_production_api_keys():
    engine = _db()
    with Session(engine) as db:
        org = Organization(name="Tenant", slug="tenant")
        db.add(org)
        db.flush()
        developer = _user(db, org, "developer-only@example.com", role="developer")
        with pytest.raises(HTTPException) as denied:
            create_developer_api_key(
                DeveloperApiKeyCreate(
                    organization_id=org.id, name="Production credential",
                    environment="production", scopes=["organization:read"],
                ), developer, db,
            )
        assert denied.value.status_code == 403
    engine.dispose()
