import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.models import AuditEvent, Membership, Organization, PortalResource, User
from app.api.portal_workflows import PortalResourceIn, create_private_resource, list_public_resources, read_private_resource


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__, Organization.__table__, Membership.__table__, AuditEvent.__table__, PortalResource.__table__])
    return engine


def test_private_portal_records_are_tenant_isolated_and_membership_revocation_applies():
    engine = _db()
    with Session(engine) as db:
        owner = User(email="owner@example.com", full_name="Owner", password_hash="unused")
        outsider = User(email="outsider@example.com", full_name="Outsider", password_hash="unused")
        org = Organization(name="Acme", slug="acme")
        db.add_all([owner, outsider, org])
        db.flush()
        membership = Membership(user_id=owner.id, organization_id=org.id, role="org_admin", is_active=True)
        db.add(membership)
        db.commit()
        created = create_private_resource("developers", PortalResourceIn(resource_type="application", title="Billing integration", organization_id=org.id), owner, db)
        assert created["visibility"] == "private"
        assert created["organization_id"] == org.id
        with pytest.raises(HTTPException) as denied:
            read_private_resource("developers", created["id"], outsider, db)
        assert denied.value.status_code == 404
        membership.is_active = False
        db.commit()
        with pytest.raises(HTTPException) as revoked:
            read_private_resource("developers", created["id"], owner, db)
        assert revoked.value.status_code == 404
    engine.dispose()


def test_public_portal_feed_exposes_only_published_global_records():
    engine = _db()
    with Session(engine) as db:
        user = User(email="editor@example.com", full_name="Editor", password_hash="unused")
        org = Organization(name="Acme", slug="acme")
        db.add_all([user, org])
        db.flush()
        db.add_all([
            PortalResource(portal="events", resource_type="event", title="Public event", summary="Published", data={}, organization_id=None, owner_user_id=user.id, visibility="public", status="published"),
            PortalResource(portal="events", resource_type="event", title="Draft event", summary="Not public", data={}, organization_id=None, owner_user_id=user.id, visibility="public", status="draft"),
            PortalResource(portal="events", resource_type="event", title="Tenant event", summary="Private tenant record", data={}, organization_id=org.id, owner_user_id=user.id, visibility="public", status="published"),
        ])
        db.commit()
        rows = list_public_resources("events", None, 30, db)
        assert [row["title"] for row in rows] == ["Public event"]
    engine.dispose()


def test_portal_resource_type_allowlist_rejects_arbitrary_modules():
    engine = _db()
    with Session(engine) as db:
        user = User(email="member@example.com", full_name="Member", password_hash="unused")
        db.add(user)
        db.commit()
        with pytest.raises(HTTPException) as denied:
            create_private_resource("status", PortalResourceIn(resource_type="payroll_record", title="Not a status item"), user, db)
        assert denied.value.status_code == 422
    engine.dispose()
