from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fastapi import HTTPException
import pytest

from app.core.database import Base
from app.core.models import User, Organization, Membership, AuditEvent
from app.core.portal_models import PortalResource
from app.api.portal_access import (
    PortalItemIn, PortalItemUpdate, create_portal_resource, list_public_resources,
    list_my_resources, read_my_resource, update_portal_resource,
)

def setup_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, Organization.__table__, Membership.__table__,
        AuditEvent.__table__, PortalResource.__table__,
    ])
    return engine

def make_user(db, email, role="customer"):
    user = User(email=email, full_name=email.split("@")[0], password_hash="hash",
                is_active=True, platform_role=role)
    db.add(user)
    db.flush()
    return user

def test_public_feed_only_returns_explicitly_published_public_records():
    engine = setup_db()
    with Session(engine) as db:
        staff = make_user(db, "staff@example.com", "platform_admin")
        public = PortalResource(portal="status", resource_type="incident",
            visibility="public", title="API maintenance", body="Planned work",
            data={}, status="published", owner_user_id=staff.id)
        private = PortalResource(portal="status", resource_type="incident",
            visibility="private", title="Private incident", body="Internal",
            data={}, status="published", owner_user_id=staff.id)
        draft = PortalResource(portal="status", resource_type="incident",
            visibility="public", title="Unpublished incident", body="Draft",
            data={}, status="draft", owner_user_id=staff.id)
        db.add_all([public, private, draft]); db.commit()
        rows = list_public_resources("status", None, 50, db)
        assert [row["title"] for row in rows] == ["API maintenance"]
    engine.dispose()

def test_organization_records_are_visible_only_to_active_members_of_that_tenant():
    engine = setup_db()
    with Session(engine) as db:
        owner = make_user(db, "owner@example.com")
        member = make_user(db, "member@example.com")
        outsider = make_user(db, "outsider@example.com")
        org = Organization(name="Acme", slug="acme")
        db.add(org); db.flush()
        db.add_all([
            Membership(user_id=owner.id, organization_id=org.id, role="org_admin", branch_scope="*", is_active=True),
            Membership(user_id=member.id, organization_id=org.id, role="viewer", branch_scope="*", is_active=True),
        ]); db.commit()
        item = create_portal_resource("events", PortalItemIn(
            resource_type="event_registration", title="Conference registration",
            organization_id=org.id, data={"event_id": "evt-1"},
        ), owner, db)
        assert item["visibility"] == "organization"
        assert len(list_my_resources("events", None, None, 100, member, db)) == 1
        assert list_my_resources("events", None, None, 100, outsider, db) == []
        with pytest.raises(HTTPException) as denied:
            read_my_resource("events", item["id"], outsider, db)
        assert denied.value.status_code == 404
    engine.dispose()

def test_personal_private_records_are_not_visible_to_other_tenant_members():
    engine = setup_db()
    with Session(engine) as db:
        owner = make_user(db, "owner@example.com")
        org_admin = make_user(db, "admin@example.com")
        org = Organization(name="Acme", slug="acme")
        db.add(org); db.flush()
        db.add(Membership(user_id=org_admin.id, organization_id=org.id,
                          role="org_admin", branch_scope="*", is_active=True))
        row = PortalResource(portal="trust", resource_type="security_report",
            visibility="private", title="Vulnerability report", body="Sensitive",
            data={}, status="submitted", owner_user_id=owner.id)
        db.add(row); db.commit()
        with pytest.raises(HTTPException) as denied:
            read_my_resource("trust", row.id, org_admin, db)
        assert denied.value.status_code == 404
    engine.dispose()

def test_confidential_reports_cannot_be_attached_to_an_organization():
    engine = setup_db()
    with Session(engine) as db:
        owner = make_user(db, "owner@example.com")
        org = Organization(name="Acme", slug="acme")
        db.add(org); db.flush()
        db.add(Membership(user_id=owner.id, organization_id=org.id,
                          role="org_admin", branch_scope="*", is_active=True))
        db.commit()
        with pytest.raises(HTTPException) as denied:
            create_portal_resource("trust", PortalItemIn(
                resource_type="security_report", title="Private vulnerability",
                organization_id=org.id,
            ), owner, db)
        assert denied.value.status_code == 422
    engine.dispose()

def test_only_platform_admin_can_publish_public_portal_content():
    engine = setup_db()
    with Session(engine) as db:
        user = make_user(db, "customer@example.com")
        with pytest.raises(HTTPException) as denied:
            create_portal_resource("docs", PortalItemIn(
                resource_type="guide", title="Public guide", visibility="public",
            ), user, db)
        assert denied.value.status_code == 403
        admin = make_user(db, "admin@example.com", "platform_admin")
        row = create_portal_resource("docs", PortalItemIn(
            resource_type="guide", title="Public guide", visibility="public",
        ), admin, db)
        update_portal_resource("docs", row["id"], PortalItemUpdate(status="published"), admin, db)
        assert list_public_resources("docs", "guide", 50, db)[0]["title"] == "Public guide"
    engine.dispose()

def test_portal_api_routes_are_registered():
    from app.main import app
    paths = set(app.openapi()["paths"])
    assert "/api/v1/portals/{portal}/public" in paths
    assert "/api/v1/portals/{portal}/me" in paths
    assert "/api/v1/portals/{portal}/items" in paths
    assert "/api/v1/portals/{portal}/items/{item_id}" in paths
