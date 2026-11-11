from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import Base
from app.core.models import AuditEvent, Branch, Membership, Organization, User
from app.core.sacco_models import SaccoMember
from app.core.sacco_schemas import SaccoKycReviewIn, SaccoMemberCreateIn
from app.services.sacco_membership import KYCConfigurationError, decrypt_kyc_payload, encrypt_kyc_payload, identity_fingerprint, request_fingerprint


def _configure_keys(monkeypatch):
    monkeypatch.setattr(settings, "sacco_kyc_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "sacco_kyc_hmac_key", "sacco-test-hmac-key-material-32-bytes-minimum")


def _payload(**overrides):
    values = {
        "member_number": " mem-0001 ", "full_name": "  Jane   Wanjiku ",
        "phone": "+254 712 345 678", "email": "JANE@example.com", "branch_id": "branch-a",
        "national_id": "12345678", "date_of_birth": "1990-01-02", "postal_address": "Nairobi",
        "idempotency_key": "sacco-member-0001",
    }
    values.update(overrides)
    return SaccoMemberCreateIn(**values)


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, Organization.__table__, Membership.__table__, Branch.__table__,
        AuditEvent.__table__, SaccoMember.__table__,
    ])
    return engine, Session(engine)


def test_sacco_member_contract_normalizes_fields_and_rejects_invalid_identity_or_phone():
    payload = _payload()
    assert payload.member_number == "MEM-0001"
    assert payload.full_name == "Jane Wanjiku"
    assert payload.phone == "+254712345678"
    assert str(payload.email) == "jane@example.com"
    assert payload.national_id == "12345678"
    with pytest.raises(ValidationError):
        _payload(national_id="123")
    with pytest.raises(ValidationError):
        _payload(phone="not-a-phone")
    with pytest.raises(ValidationError):
        _payload(date_of_birth=date.today().isoformat())
    with pytest.raises(ValidationError):
        SaccoKycReviewIn(decision="approve", note="Review complete")


def test_kyc_is_encrypted_and_identity_fingerprint_is_keyed(monkeypatch):
    _configure_keys(monkeypatch)
    raw_id = "12345678"
    ciphertext = encrypt_kyc_payload({"national_id": raw_id, "date_of_birth": "1990-01-02"})
    fingerprint = identity_fingerprint(raw_id)
    assert raw_id not in ciphertext
    assert raw_id not in fingerprint
    assert decrypt_kyc_payload(ciphertext)["national_id"] == raw_id
    assert fingerprint == identity_fingerprint("1234-5678")
    assert request_fingerprint({"member": "MEM-0001"}) == request_fingerprint({"member": "MEM-0001"})
    assert request_fingerprint({"member": "MEM-0001"}) != request_fingerprint({"member": "MEM-0002"})


def test_kyc_fails_closed_when_encryption_or_hmac_key_is_missing(monkeypatch):
    monkeypatch.setattr(settings, "sacco_kyc_encryption_key", "")
    monkeypatch.setattr(settings, "sacco_kyc_hmac_key", "")
    with pytest.raises(KYCConfigurationError):
        encrypt_kyc_payload({"national_id": "12345678"})
    with pytest.raises(KYCConfigurationError):
        identity_fingerprint("12345678")


def test_sacco_member_model_constraints_and_route_registration():
    assert SaccoMember.__tablename__ == "sacco_members"
    assert {"uq_sacco_member_org_number", "uq_sacco_member_org_identity", "uq_sacco_member_org_idempotency"} <= {
        item.name for item in SaccoMember.__table__.constraints if item.name
    }
    from app.main import app
    paths = set(app.openapi()["paths"])
    assert "/api/v1/sacco/members" in paths
    assert "/api/v1/sacco/members/{member_id}" in paths
    assert "/api/v1/sacco/members/{member_id}/kyc-details" in paths
    assert "/api/v1/sacco/members/{member_id}/kyc-review" in paths
    assert "/sacco" in paths


def test_member_creation_idempotency_branch_scope_and_four_eyes_kyc_review(monkeypatch):
    _configure_keys(monkeypatch)
    from app.api.sacco import create_member, get_member, get_member_kyc_details, review_member_kyc
    engine, db = _database()
    try:
        creator = User(email="creator@example.test", full_name="Creator", password_hash="unused")
        reviewer = User(email="reviewer@example.test", full_name="Reviewer", password_hash="unused")
        org = Organization(name="SACCO tenant", slug="sacco-tenant")
        db.add_all([creator, reviewer, org])
        db.flush()
        branch = Branch(id="branch-a", organization_id=org.id, code="HQ", name="Head Office")
        db.add(branch)
        db.commit()
        officer = SimpleNamespace(organization_id=org.id, role="sacco_officer", branch_scope="*")
        approver = SimpleNamespace(organization_id=org.id, role="sacco_kyc_approver", branch_scope="*")
        created = create_member(_payload(), creator, officer, db)
        assert created["status"] == "pending_kyc" and created["replayed"] is False
        replay = create_member(_payload(), creator, officer, db)
        assert replay["id"] == created["id"] and replay["replayed"] is True
        safe = get_member(created["id"], officer, db)
        assert "identity_ciphertext" not in safe and "national_id" not in safe
        with pytest.raises(HTTPException) as self_review:
            review_member_kyc(created["id"], SaccoKycReviewIn(decision="verify", note="KYC verified"), creator, approver, db)
        assert self_review.value.status_code == 403
        with pytest.raises(HTTPException) as no_access:
            review_member_kyc(created["id"], SaccoKycReviewIn(decision="verify", note="KYC verified"), reviewer, approver, db)
        assert no_access.value.status_code == 409
        details = get_member_kyc_details(created["id"], "Identity document and date of birth checked", reviewer, approver, db)
        assert details["national_id"] == "12345678"
        reviewed = review_member_kyc(created["id"], SaccoKycReviewIn(decision="verify", note="Identity verified against source document"), reviewer, approver, db)
        assert reviewed["status"] == "active" and reviewed["reviewed_by"] == reviewer.id
        assert db.query(AuditEvent).filter_by(action="sacco.member.kyc_details_accessed").count() == 1
        assert db.query(AuditEvent).filter_by(action="sacco.member.kyc_reviewed").count() == 1

        rejected_payload = _payload(member_number="MEM-0002", national_id="87654321", idempotency_key="sacco-member-0002")
        rejected_member = create_member(rejected_payload, creator, officer, db)
        get_member_kyc_details(rejected_member["id"], "Second identity document review", reviewer, approver, db)
        rejected = review_member_kyc(
            rejected_member["id"],
            SaccoKycReviewIn(decision="reject", note="Identity document could not be verified"),
            reviewer, approver, db,
        )
        assert rejected["status"] == "rejected"
        with pytest.raises(HTTPException) as second_decision:
            review_member_kyc(
                rejected_member["id"],
                SaccoKycReviewIn(decision="verify", note="Attempted second decision"),
                reviewer, approver, db,
            )
        assert second_decision.value.status_code == 409

        with pytest.raises(HTTPException) as duplicate_identity:
            create_member(
                _payload(member_number="MEM-0003", idempotency_key="sacco-member-0003"),
                creator, officer, db,
            )
        assert duplicate_identity.value.status_code == 409
        with pytest.raises(HTTPException) as duplicate_number:
            create_member(
                _payload(member_number="MEM-0001", national_id="11223344", idempotency_key="sacco-member-0004"),
                creator, officer, db,
            )
        assert duplicate_number.value.status_code == 409
        other_org = Organization(name="Other tenant", slug="other-tenant")
        db.add(other_org)
        db.commit()
        other_membership = SimpleNamespace(organization_id=other_org.id, role="sacco_auditor", branch_scope="*")
        with pytest.raises(HTTPException) as cross_tenant:
            get_member(created["id"], other_membership, db)
        assert cross_tenant.value.status_code == 404
        restricted = SimpleNamespace(organization_id=org.id, role="sacco_officer", branch_scope="branch-other")
        with pytest.raises(HTTPException) as wrong_branch:
            create_member(_payload(idempotency_key="sacco-member-0002"), creator, restricted, db)
        assert wrong_branch.value.status_code == 404
    finally:
        db.close()
        engine.dispose()


def test_sacco_migration_is_chained_reversible_and_forces_tenant_rls():
    migration = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0066_sacco_membership_kyc.py"
    source = migration.read_text(encoding="utf-8")
    assert 'revision = "0066_sacco_membership_kyc"' in source
    assert 'down_revision = "0065_identity_email_outbox"' in source
    assert "def upgrade():" in source and "def downgrade():" in source
    assert "ENABLE ROW LEVEL SECURITY" in source and "FORCE ROW LEVEL SECURITY" in source
    assert "sacco_member_tenant_scope" in source


def test_sacco_workspace_exposes_member_and_kyc_controls():
    page = Path(__file__).resolve().parents[1] / "app" / "web" / "sacco.html"
    html = page.read_text(encoding="utf-8")
    assert 'id="member"' in html and 'id="members"' in html and 'id="kycDetails"' in html
    assert "/sacco/members" in html
    assert "Powered by OneCore Technologies Ltd" in html

def test_sacco_roles_are_assignable_through_tenant_invitations():
    from app.api.platform_routes import InvitationIn

    for role in ("sacco_officer", "sacco_manager", "sacco_kyc_approver", "sacco_treasurer", "sacco_auditor"):
        assert InvitationIn(email="member@example.com", role=role).role == role


def test_sacco_roles_are_least_privilege():
    from app.core.authorization import require_permission
    from fastapi import HTTPException

    require_permission(SimpleNamespace(role="sacco_officer"), "create")
    require_permission(SimpleNamespace(role="sacco_auditor"), "read")
    require_permission(SimpleNamespace(role="sacco_kyc_approver"), "manage")
    with pytest.raises(HTTPException):
        require_permission(SimpleNamespace(role="sacco_officer"), "manage")
    with pytest.raises(HTTPException):
        require_permission(SimpleNamespace(role="sacco_auditor"), "create")


def test_sacco_workspace_supports_mfa_challenge_and_never_persists_token():
    page = Path(__file__).resolve().parents[1] / "app" / "web" / "sacco.html"
    html = page.read_text(encoding="utf-8")
    assert 'name="mfa_code"' in html
    assert "/api/v1/auth/mfa/challenge" in html
    assert "sessionStorage" not in html and "localStorage" not in html
