from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from pydantic import ValidationError
import pytest

from app.core.database import Base
from app.core.models import Membership, Organization, SupportAttachment, SupportMessage, SupportTicket, User, AuditEvent
from app.core.schemas import SupportMessageIn, SupportTicketCreateIn
from app.api.support import _create_ticket, _guest_ticket, _user_ticket


def test_support_tables_and_indexes_are_registered():
    assert SupportTicket.__tablename__ == "support_tickets"
    assert SupportMessage.__tablename__ == "support_messages"
    assert SupportAttachment.__tablename__ == "support_attachments"
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
        SupportMessage.__table__, SupportAttachment.__table__, AuditEvent.__table__,
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
    assert "/api/v1/support/tickets/{ticket_number}/attachments" in paths
    assert "/api/v1/support/tickets/{ticket_number}/attachments/{attachment_id}/complete" in paths
    assert "/api/v1/support/tickets/{ticket_number}/attachments/{attachment_id}/download" in paths
    assert "/api/v1/support/admin/tickets/{ticket_number}/attachments/{attachment_id}/scan" in paths


def test_support_organization_ticket_owner_loses_access_when_membership_is_revoked():
    from fastapi import HTTPException

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, Organization.__table__, Membership.__table__,
        SupportTicket.__table__, SupportMessage.__table__, AuditEvent.__table__,
    ])
    with Session(engine) as db:
        org = Organization(name="Tenant A", slug="tenant-a")
        db.add(org)
        db.flush()
        owner = User(email="owner@example.com", full_name="Owner", password_hash="unused")
        admin = User(email="admin@example.com", full_name="Admin", password_hash="unused")
        db.add_all([owner, admin])
        db.flush()
        owner_membership = Membership(user_id=owner.id, organization_id=org.id, role="staff", is_active=True)
        admin_membership = Membership(user_id=admin.id, organization_id=org.id, role="org_admin", is_active=True)
        db.add_all([owner_membership, admin_membership])
        ticket = SupportTicket(
            ticket_number="OCS-TENANT0001", subject="Tenant issue", category="technical",
            contact_name="Owner", contact_email="owner@example.com", organization_id=org.id,
            created_by_user_id=owner.id,
        )
        db.add(ticket)
        db.commit()
        assert _user_ticket(db, ticket.ticket_number, owner).id == ticket.id
        assert _user_ticket(db, ticket.ticket_number, admin).id == ticket.id
        owner_membership.is_active = False
        db.commit()
        with pytest.raises(HTTPException) as denied:
            _user_ticket(db, ticket.ticket_number, owner)
        assert denied.value.status_code == 404
        assert _user_ticket(db, ticket.ticket_number, admin).id == ticket.id
    engine.dispose()


def test_support_rls_migration_is_part_of_the_alembic_chain():
    from pathlib import Path

    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0054_support_row_level_security.py"
    source = migration.read_text()
    assert 'revision = "0054_support_row_level_security"' in source
    assert 'down_revision = "0053_user_mfa"' in source
    assert "support_ticket_select" in source
    assert "support_message_insert" in source
    assert "ENABLE ROW LEVEL SECURITY" in source


def test_support_attachment_metadata_constraints_and_safe_filename():
    from pydantic import ValidationError
    from app.api.support import SupportAttachmentIntent, _safe_attachment_name

    valid = SupportAttachmentIntent(
        file_name="evidence.pdf", content_type="application/pdf", size_bytes=1024,
    )
    assert valid.file_name == "evidence.pdf"
    assert _safe_attachment_name("../../evidence.pdf") == "evidence.pdf"
    assert _safe_attachment_name('evil";x.pdf') == "evil__x.pdf"
    with pytest.raises(ValidationError):
        SupportAttachmentIntent(
            file_name="large.pdf", content_type="application/pdf", size_bytes=11 * 1024 * 1024,
        )
    with pytest.raises(Exception):
        _safe_attachment_name("../")


def test_support_attachment_migration_follows_support_rls_and_quarantines_metadata():
    from pathlib import Path

    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0055_support_attachments.py"
    source = migration.read_text()
    assert 'revision = "0055_support_attachments"' in source
    assert 'down_revision = "0054_support_row_level_security"' in source
    assert "support_attachment_select" in source
    assert "support_attachment_insert" in source
    assert "support_attachment_update" in source


def test_support_attachments_remain_quarantined_until_security_review():
    from fastapi import HTTPException
    from app.api.support import _attachment_download

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, Organization.__table__, SupportTicket.__table__,
        SupportMessage.__table__, SupportAttachment.__table__, AuditEvent.__table__,
    ])
    with Session(engine) as db:
        ticket = SupportTicket(
            ticket_number="OCS-QUARANTINE1", subject="Attachment review", category="technical",
            contact_name="Owner", contact_email="owner@example.com",
        )
        db.add(ticket)
        db.flush()
        pending = SupportAttachment(
            ticket_id=ticket.id, file_name="evidence.pdf", object_key="support/test/object",
            content_type="application/pdf", size_bytes=128, status="pending_scan",
        )
        db.add(pending)
        db.commit()
        with pytest.raises(HTTPException) as denied:
            _attachment_download(pending)
        assert denied.value.status_code == 409
        assert "security review" in denied.value.detail
    engine.dispose()


def test_clamav_scan_response_parser_requires_explicit_verdict():
    from app.api.support import _parse_clamav_response
    assert _parse_clamav_response('stream: OK' + chr(0)) == ('clean', None)
    assert _parse_clamav_response('stream: Eicar-Test-Signature FOUND' + chr(0)) == ('infected', 'Eicar-Test-Signature')
    with pytest.raises(RuntimeError):
        _parse_clamav_response('stream: ERROR' + chr(0))


def test_support_attachment_scan_evidence_migration_follows_webhooks():
    from pathlib import Path
    migration = Path(__file__).parents[1] / 'migrations' / 'versions' / '0058_support_attachment_scan_evidence.py'
    source = migration.read_text()
    assert 'revision = "0058_support_attachment_scan_evidence"' in source
    assert 'down_revision = "0057_developer_webhooks"' in source
    for column in ('scan_engine', 'scan_result', 'scan_signature', 'scanned_at'):
        assert column in source
