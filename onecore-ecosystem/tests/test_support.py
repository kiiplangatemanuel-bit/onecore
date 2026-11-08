from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from pydantic import ValidationError
import pytest

from app.core.database import Base
from app.core.models import Organization, SupportMessage, SupportTicket, User, AuditEvent
from app.core.schemas import SupportMessageIn, SupportTicketCreateIn
from app.api.support import _create_ticket, _guest_ticket


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
        import hashlib
        raw_token = "a" * 48
        ticket = _create_ticket(payload, db, guest_token_hash=hashlib.sha256(raw_token.encode()).hexdigest())
        assert ticket.ticket_number.startswith("OCS-")
        assert ticket.guest_token_hash != raw_token
        assert _guest_ticket(db, ticket.ticket_number, raw_token).id == ticket.id
        from fastapi import HTTPException
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
