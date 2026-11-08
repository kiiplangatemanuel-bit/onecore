from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.models import AuditEvent, Membership, Organization, PortalWorkflowRecord, User
from app.api.portal_workflows import (
    PortalRecordCreate, PortalRecordUpdate, create_portal_record,
    list_portal_records, list_public_portal_content, read_portal_record,
    update_portal_record, PortalPublicContentCreate, publish_public_portal_content,
)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, Organization.__table__, Membership.__table__,
        AuditEvent.__table__, PortalWorkflowRecord.__table__,
    ])
    return engine


def _identity(db, email, org, role="staff"):
    user = User(email=email, full_name=email.split("@")[0], password_hash="unused")
    db.add(user)
    db.flush()
    membership = Membership(user_id=user.id, organization_id=org.id, role=role, is_active=True)
    db.add(membership)
    db.flush()
    return user


def test_portal_records_are_tenant_scoped_and_private_records_are_owner_only():
    engine = _db()
    with Session(engine) as db:
        org_a = Organization(name="A", slug="org-a")
        org_b = Organization(name="B", slug="org-b")
        db.add_all([org_a, org_b])
        db.flush()
        owner = _identity(db, "owner@example.com", org_a, "org_admin")
        colleague = _identity(db, "colleague@example.com", org_a, "staff")
        other_tenant = _identity(db, "other@example.com", org_b, "org_admin")
        db.commit()

        private = create_portal_record(
            "community", "post",
            PortalRecordCreate(organization_id=org_a.id, visibility="private",
                               payload={"title": "Private", "body": "Owner only"}),
            owner, db,
        )
        shared = create_portal_record(
            "community", "post",
            PortalRecordCreate(organization_id=org_a.id, visibility="organization",
                               payload={"title": "Shared", "body": "Org members"}),
            owner, db,
        )
        assert [row["id"] for row in list_portal_records(
            "community", "post", org_a.id, 50, colleague, db
        )] == [shared["id"]]
        assert list_portal_records("community", "post", org_b.id, 50, other_tenant, db) == []
        with pytest.raises(HTTPException) as cross_tenant:
            read_portal_record("community", shared["id"], other_tenant, db)
        assert cross_tenant.value.status_code == 404
        with pytest.raises(HTTPException) as private_denied:
            read_portal_record("community", private["id"], colleague, db)
        assert private_denied.value.status_code == 404
        assert read_portal_record("community", private["id"], owner, db)["id"] == private["id"]
    engine.dispose()


def test_confidential_trust_and_careers_records_are_personal_and_not_org_scoped():
    engine = _db()
    with Session(engine) as db:
        org = Organization(name="A", slug="org-a")
        db.add(org)
        db.flush()
        owner = _identity(db, "owner@example.com", org, "org_admin")
        colleague = _identity(db, "colleague@example.com", org, "org_admin")
        db.commit()

        with pytest.raises(HTTPException) as invalid_visibility:
            create_portal_record(
                "trust", "security_report",
                PortalRecordCreate(visibility="organization",
                                   payload={"title": "Disclosure", "description": "Details", "severity": "high"}),
                owner, db,
            )
        assert invalid_visibility.value.status_code == 422

        report = create_portal_record(
            "trust", "security_report",
            PortalRecordCreate(payload={"title": "Disclosure", "description": "Details", "severity": "high"}),
            owner, db,
        )
        assert report["status"] == "submitted"
        assert list_portal_records("trust", "security_report", None, 50, colleague, db) == []
        with pytest.raises(HTTPException) as denied:
            read_portal_record("trust", report["id"], colleague, db)
        assert denied.value.status_code == 404
    engine.dispose()


def test_public_portal_content_returns_only_published_public_global_records():
    engine = _db()
    with Session(engine) as db:
        admin = User(email="admin@example.com", full_name="Admin", password_hash="unused",
                     platform_role="platform_admin")
        db.add(admin)
        db.flush()
        db.add_all([
            PortalWorkflowRecord(portal_key="events", record_type="event", owner_user_id=admin.id,
                                 organization_id=None, visibility="public", status="published",
                                 payload={"title": "Public webinar"}),
            PortalWorkflowRecord(portal_key="events", record_type="event", owner_user_id=admin.id,
                                 organization_id=None, visibility="public", status="draft",
                                 payload={"title": "Draft webinar"}),
            PortalWorkflowRecord(portal_key="events", record_type="event", owner_user_id=admin.id,
                                 organization_id=None, visibility="organization", status="published",
                                 payload={"title": "Private event"}),
        ])
        db.commit()
        result = list_public_portal_content("events", "event", 50, db)
        assert [row["payload"]["title"] for row in result] == ["Public webinar"]
        with pytest.raises(HTTPException):
            list_public_portal_content("events", "security_report", 50, db)
    engine.dispose()


def test_owner_cannot_change_confidential_case_status():
    engine = _db()
    with Session(engine) as db:
        owner = User(email="owner@example.com", full_name="Owner", password_hash="unused")
        db.add(owner)
        db.commit()
        report = create_portal_record(
            "trust", "security_report",
            PortalRecordCreate(payload={"title": "Disclosure", "description": "Details", "severity": "high"}),
            owner, db,
        )
        with pytest.raises(HTTPException) as denied:
            update_portal_record("trust", report["id"], PortalRecordUpdate(status="resolved"), owner, db)
        assert denied.value.status_code == 403
    engine.dispose()


def test_portal_workflow_routes_are_registered():
    from app.main import app
    paths = set(app.openapi()["paths"])
    assert "/api/v1/portals/{portal}/public/{record_type}" in paths
    assert "/api/v1/portals/{portal}/records/{record_type}" in paths
    assert "/api/v1/portals/admin/{portal}/public/{record_type}" in paths


def test_public_content_publication_requires_platform_admin():
    engine = _db()
    with Session(engine) as db:
        customer = User(email="customer@example.com", full_name="Customer", password_hash="unused")
        admin = User(email="admin@example.com", full_name="Admin", password_hash="unused",
                     platform_role="platform_admin")
        db.add_all([customer, admin])
        db.commit()
        payload = PortalPublicContentCreate(payload={
            "title": "Service incident", "service": "API", "severity": "minor",
            "summary": "A short public update",
        })
        with pytest.raises(HTTPException) as denied:
            publish_public_portal_content("status", "incident", payload, customer, db)
        assert denied.value.status_code == 403
        published = publish_public_portal_content("status", "incident", payload, admin, db)
        assert published["visibility"] == "public"
        assert published["status"] == "published"
        assert len(list_public_portal_content("status", "incident", 50, db)) == 1
    engine.dispose()
