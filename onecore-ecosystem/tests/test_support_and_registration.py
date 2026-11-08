from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import pytest
from pydantic import ValidationError

from app.core.database import Base
from app.core.models import (
    AuditEvent, EmailVerification, Membership, Organization, SupportMessage,
    SupportTicket, User,
)
from app.core.schemas import (
    EmailVerificationIn, OrganizationRegistrationIn, SupportMessageIn,
    SupportTicketCreateIn,
)
from app.api.support import _create_ticket, _guest_ticket
from app.api.auth_workflows import register_organization, verify_email


def test_support_tables_and_indexes_are_registered():
    assert SupportTicket.__tablename__ == "support_tickets"
    assert SupportMessage.__tablename__ == "support_messages"
    assert "ix_support_tickets_ticket_number" in {i.name for i in SupportTicket.__table__.indexes}
    assert "ix_support_message_ticket_created" in {i.name for i in SupportMessage.__table__.indexes}


def test_support_schemas_validate_email_and_message_lengths():
    ticket = SupportTicketCreateIn(
        subject="Cannot access workspace", category="technical",
        message="I cannot access my organization workspace after signing in.",
        contact_name="Jane Doe", contact_email="jane@example.com",
    )
    assert ticket.category == "technical"
    assert SupportMessageIn(body="Additional diagnostic details").body.startswith("Additional")
    with pytest.raises(ValidationError):
        SupportTicketCreateIn(
            subject="No", message="Short", contact_name="Jane",
            contact_email="not-an-email",
        )


def test_public_ticket_persists_hashed_guest_token_and_rejects_wrong_token():
    import hashlib
    from fastapi import HTTPException
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, Organization.__table__, SupportTicket.__table__,
        SupportMessage.__table__, AuditEvent.__table__,
    ])
    with Session(engine) as db:
        payload = SupportTicketCreateIn(
            subject="Cannot sign in", category="account",
            message="I cannot sign in to my OneCore account.",
            contact_name="Guest User", contact_email="guest@example.com",
        )
        raw_token = "a" * 48
        ticket = _create_ticket(payload, db, guest_token_hash=hashlib.sha256(raw_token.encode()).hexdigest())
        assert ticket.ticket_number.startswith("OCS-")
        assert ticket.guest_token_hash != raw_token
        assert _guest_ticket(db, ticket.ticket_number, raw_token).id == ticket.id
        with pytest.raises(HTTPException) as denied:
            _guest_ticket(db, ticket.ticket_number, "b" * 48)
        assert denied.value.status_code == 404
    engine.dispose()


def test_support_routes_are_registered():
    from app.main import app
    paths = set(app.openapi()["paths"])
    assert "/api/v1/support/public/tickets" in paths
    assert "/api/v1/support/tickets" in paths
    assert "/api/v1/support/admin/tickets" in paths
    assert "/api/v1/support/admin/tickets/{ticket_number}" in paths


def test_registration_schema_requires_strong_password_and_valid_slug():
    payload = OrganizationRegistrationIn(
        organization_name="Example Limited", organization_slug="example-limited",
        full_name="Jane Doe", email="jane@example.com", password="long-secure-password",
    )
    assert payload.country == "KE"
    with pytest.raises(ValidationError):
        OrganizationRegistrationIn(
            organization_name="Example Limited", organization_slug="bad slug",
            full_name="Jane Doe", email="jane@example.com", password="short",
        )


def test_registration_creates_inactive_user_and_verification_activates_it(monkeypatch):
    import app.api.auth_workflows as workflows
    sent = {}
    monkeypatch.setattr(workflows, "_send_verification_email",
                        lambda email, full_name, token: sent.update(email=email, token=token))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, Organization.__table__, Membership.__table__,
        EmailVerification.__table__, AuditEvent.__table__,
    ])
    with Session(engine) as db:
        payload = OrganizationRegistrationIn(
            organization_name="Example Limited", organization_slug="example-limited",
            full_name="Jane Doe", email="jane@example.com", password="long-secure-password",
            phone="+254700000000",
        )
        result = register_organization(payload, db)
        user = db.query(User).filter_by(email="jane@example.com").one()
        assert result["status"] == "verification_required"
        assert user.is_active is False
        assert user.phone == "+254700000000"
        assert db.query(Membership).filter_by(user_id=user.id, role="org_admin").count() == 1
        verified = verify_email(EmailVerificationIn(token=sent["token"]), db)
        assert verified["status"] == "verified"
        assert db.get(User, user.id).is_active is True
        with pytest.raises(Exception):
            verify_email(EmailVerificationIn(token=sent["token"]), db)
    engine.dispose()


def test_registration_and_verification_routes_are_registered():
    from app.main import app
    paths = set(app.openapi()["paths"])
    assert "/api/v1/auth/register-organization" in paths
    assert "/api/v1/auth/verify-email" in paths



def test_registration_route_keeps_json_request_body_contract():
    from app.main import app

    operation = app.openapi()["paths"]["/api/v1/auth/register-organization"]["post"]
    assert "requestBody" in operation
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/OrganizationRegistrationIn")
