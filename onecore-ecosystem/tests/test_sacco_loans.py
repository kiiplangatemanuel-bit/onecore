from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.models import AuditEvent, Branch, Membership, Organization, User
from app.core.sacco_models import SaccoMember
from app.core.sacco_loan_models import (
    SaccoLoanApplication, SaccoLoanCollateral, SaccoLoanDisbursement,
    SaccoLoanGuarantor, SaccoLoanInstallment, SaccoLoanProduct,
    SaccoLoanRepayment, SaccoLoanRepaymentAllocation, SaccoLoanRepaymentJournalLine,
)
from app.core.sacco_loan_schemas import (
    SaccoLoanApplicationCreateIn, SaccoLoanAssessmentIn, SaccoLoanCollateralCreateIn,
    SaccoLoanCollateralVerificationIn, SaccoLoanDecisionIn, SaccoLoanDisbursementCreateIn,
    SaccoLoanDisbursementVerificationIn, SaccoLoanGuarantorConsentIn,
    SaccoLoanGuarantorCreateIn, SaccoLoanProductCreateIn,
    SaccoLoanRepaymentCreateIn, SaccoLoanRepaymentVerificationIn,
)


def _database():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[
        User.__table__, Organization.__table__, Membership.__table__, Branch.__table__,
        AuditEvent.__table__, SaccoMember.__table__, SaccoLoanProduct.__table__,
        SaccoLoanApplication.__table__, SaccoLoanGuarantor.__table__,
        SaccoLoanCollateral.__table__, SaccoLoanInstallment.__table__,
        SaccoLoanDisbursement.__table__, SaccoLoanRepayment.__table__,
        SaccoLoanRepaymentAllocation.__table__, SaccoLoanRepaymentJournalLine.__table__,
    ])
    return engine, Session(engine)


def _seed(db: Session, *, branch_id=None):
    creator = User(email="loan-creator@example.test", full_name="Loan Creator", password_hash="unused")
    manager = User(email="loan-manager@example.test", full_name="Loan Manager", password_hash="unused")
    approver = User(email="loan-approver@example.test", full_name="Loan Approver", password_hash="unused")
    organization = Organization(name="SACCO Loans", slug="sacco-loan-test", currency="KES")
    db.add_all([creator, manager, approver, organization])
    db.flush()
    if branch_id:
        db.add(Branch(id=branch_id, organization_id=organization.id, code=branch_id.upper(),
                      name="Loan branch", is_active=True))
        db.flush()
    borrower = SaccoMember(
        organization_id=organization.id, branch_id=branch_id,
        member_number="BORROWER-001", full_name="Jane Borrower", email=None,
        phone="+254700000001", identity_fingerprint="a" * 64,
        identity_ciphertext="encrypted-test", status="active", review_note="",
        reviewed_by=None, reviewed_at=None, created_by=creator.id,
        idempotency_key="borrower-member-0001", request_fingerprint="b" * 64,
    )
    guarantor = SaccoMember(
        organization_id=organization.id, branch_id=branch_id,
        member_number="GUARANTOR-001", full_name="John Guarantor", email=None,
        phone="+254700000002", identity_fingerprint="c" * 64,
        identity_ciphertext="encrypted-test", status="active", review_note="",
        reviewed_by=None, reviewed_at=None, created_by=creator.id,
        idempotency_key="guarantor-member-0001", request_fingerprint="d" * 64,
    )
    db.add_all([borrower, guarantor])
    db.commit()
    return creator, manager, approver, organization, borrower, guarantor


def _membership(organization_id, role, branch_scope="*"):
    return SimpleNamespace(organization_id=organization_id, role=role, branch_scope=branch_scope)


def _product_payload(**overrides):
    values = {
        "code": "DEV-LOAN", "name": "Development Loan", "currency": "KES",
        "minimum_principal": "1000.00", "maximum_principal": "50000.00",
        "annual_interest_rate_bps": 1200, "minimum_term_months": 3,
        "maximum_term_months": 36, "minimum_guarantors": 1,
        "maximum_debt_service_ratio_bps": 4000, "requires_collateral": True,
    }
    values.update(overrides)
    return SaccoLoanProductCreateIn(**values)


def _application_payload(member_id, product_id, **overrides):
    values = {
        "member_id": member_id, "product_id": product_id, "principal": "10000.00",
        "term_months": 12, "purpose": "Purchase equipment for member business",
        "monthly_net_income": "30000.00", "monthly_existing_debt": "0.00",
        "first_repayment_date": date.today() + timedelta(days=35),
        "idempotency_key": "loan-application-0001",
    }
    values.update(overrides)
    return SaccoLoanApplicationCreateIn(**values)


def _create_product(db, user, organization):
    from app.api.sacco_loans import create_loan_product
    return create_loan_product(
        _product_payload(), user, _membership(organization.id, "sacco_manager"), db
    )


def _create_application(db, creator, organization, borrower, product_id, **overrides):
    from app.api.sacco_loans import create_loan_application
    return create_loan_application(
        _application_payload(borrower.id, product_id, **overrides),
        creator, _membership(organization.id, "sacco_officer"), db,
    )


def test_loan_product_contract_normalizes_and_rejects_invalid_ranges():
    payload = _product_payload(code=" dev_loan ", name="  Development   Loan ")
    assert payload.code == "DEV_LOAN"
    assert payload.name == "Development Loan"
    with pytest.raises(ValidationError):
        _product_payload(minimum_principal="10000", maximum_principal="9000")
    with pytest.raises(ValidationError):
        _product_payload(minimum_term_months=24, maximum_term_months=12)
    with pytest.raises(ValidationError):
        _product_payload(annual_interest_rate_bps=7000)
    with pytest.raises(ValidationError):
        _product_payload(maximum_debt_service_ratio_bps=9500)


def test_loan_application_contract_requires_future_due_date_and_safe_financial_inputs():
    with pytest.raises(ValidationError):
        _application_payload(1, 1, first_repayment_date=date.today())
    with pytest.raises(ValidationError):
        _application_payload(1, 1, monthly_net_income="0")
    with pytest.raises(ValidationError):
        _application_payload(1, 1, monthly_existing_debt="-1")
    with pytest.raises(ValidationError):
        _application_payload(1, 1, purpose="short")


def test_loan_disbursement_contract_normalizes_and_rejects_invalid_evidence():
    payload = SaccoLoanDisbursementCreateIn(
        amount="1000.00", currency="kes", channel="bank_transfer",
        external_reference="  BANK-REF-001  ", value_date=date.today(),
        request_note="  Approved bank evidence reviewed  ",
        idempotency_key="  loan-disbursement-key-001  ",
    )
    assert payload.currency == "KES"
    assert payload.external_reference == "BANK-REF-001"
    assert payload.request_note == "Approved bank evidence reviewed"
    assert payload.idempotency_key == "loan-disbursement-key-001"

    with pytest.raises(ValidationError):
        SaccoLoanDisbursementCreateIn(
            amount="1000.00", currency="KES", channel="unsupported",
            external_reference="BANK-REF-002", value_date=date.today(),
            request_note="Valid request note", idempotency_key="loan-disbursement-key-002",
        )
    with pytest.raises(ValidationError):
        SaccoLoanDisbursementCreateIn(
            amount="1000.00", currency="KES", channel="cash",
            external_reference="CASH-REF-001", value_date=date.today() + timedelta(days=1),
            request_note="Valid request note", idempotency_key="loan-disbursement-key-003",
        )


def test_loan_origination_requires_independent_assessment_guarantor_consent_and_collateral():
    from app.api.sacco_loans import (
        add_loan_collateral, add_loan_guarantor, assess_loan_application,
        decide_loan_application, get_loan_schedule, record_loan_guarantor_consent,
        verify_loan_collateral,
    )

    engine, db = _database()
    try:
        creator, manager, approver, org, borrower, guarantor = _seed(db)
        product = _create_product(db, manager, org)
        application = _create_application(db, creator, org, borrower, product["id"])
        assert application["status"] == "pending_assessment"

        guarantee = add_loan_guarantor(
            application["id"], SaccoLoanGuarantorCreateIn(
                member_id=guarantor.id, guaranteed_amount="10000.00"
            ), creator, _membership(org.id, "sacco_officer"), db,
        )
        assert guarantee["consent_status"] == "pending"

        collateral = add_loan_collateral(
            application["id"], SaccoLoanCollateralCreateIn(
                collateral_type="equipment", description="Workshop production equipment",
                declared_value="15000.00", document_reference="COLLATERAL-DOC-001",
            ), creator, _membership(org.id, "sacco_officer"), db,
        )
        assert collateral["status"] == "pending_verification"

        with pytest.raises(HTTPException) as self_consent:
            record_loan_guarantor_consent(
                guarantee["id"], SaccoLoanGuarantorConsentIn(
                    decision="accept", consent_reference="SIGNED-FORM-001", note="Signed in person"
                ), creator, _membership(org.id, "sacco_manager"), db,
            )
        assert self_consent.value.status_code == 403

        verifier_membership = _membership(org.id, "sacco_guarantor_verifier")
        accepted = record_loan_guarantor_consent(
            guarantee["id"], SaccoLoanGuarantorConsentIn(
                decision="accept", consent_reference="SIGNED-FORM-001",
                note="Original signed guarantee form checked",
            ), manager, verifier_membership, db,
        )
        assert accepted["consent_status"] == "accepted"
        verified = verify_loan_collateral(
            collateral["id"], SaccoLoanCollateralVerificationIn(
                decision="verify", note="Ownership and valuation document checked"
            ), manager, verifier_membership, db,
        )
        assert verified["status"] == "verified"

        assessed = assess_loan_application(
            application["id"], SaccoLoanAssessmentIn(note="Income and existing debt evidence reviewed"),
            manager, _membership(org.id, "sacco_credit_officer"), db,
        )
        assert assessed["assessment_status"] == "eligible"
        assert assessed["status"] == "pending_approval"
        assert assessed["estimated_monthly_installment"] is not None

        with pytest.raises(HTTPException) as assessor_cannot_approve:
            decide_loan_application(
                application["id"], SaccoLoanDecisionIn(
                    decision="approve", note="Approve after independent review"
                ), manager, _membership(org.id, "sacco_credit_approver"), db,
            )
        assert assessor_cannot_approve.value.status_code == 403

        approved = decide_loan_application(
            application["id"], SaccoLoanDecisionIn(
                decision="approve", note="Independent credit approval recorded"
            ), approver, _membership(org.id, "sacco_credit_approver"), db,
        )
        assert approved["status"] == "approved_pending_disbursement"
        schedule = get_loan_schedule(
            application["id"], _membership(org.id, "sacco_auditor"), db
        )
        assert schedule["schedule_type"] == "projected_until_verified_disbursement"
        assert len(schedule["items"]) == 12
        assert sum((Decimal(row["principal_due"]) for row in schedule["items"]), Decimal("0")) == Decimal("10000.00")
        assert all(row["status"] == "projected" for row in schedule["items"])
        assert all(Decimal(row["interest_due"]) >= 0 for row in schedule["items"])
        assert len({row["due_date"] for row in schedule["items"]}) == 12
        events = db.query(AuditEvent).filter(
            AuditEvent.organization_id == org.id,
            AuditEvent.resource_type == "sacco_loan_application",
        ).all()
        assert {event.action for event in events} >= {
            "sacco.loan_application.created", "sacco.loan_application.assessed",
            "sacco.loan_application.decided",
        }
    finally:
        db.close()
        engine.dispose()


def test_loan_assessment_blocks_excessive_debt_service_ratio_from_approval():
    from app.api.sacco_loans import assess_loan_application, decide_loan_application

    engine, db = _database()
    try:
        creator, manager, approver, org, borrower, guarantor = _seed(db)
        product = _create_product(db, manager, org)
        application = _create_application(
            db, creator, org, borrower, product["id"],
            monthly_net_income="1000.00", monthly_existing_debt="500.00",
        )
        assessed = assess_loan_application(
            application["id"], SaccoLoanAssessmentIn(note="Income and debt documents reviewed"),
            manager, _membership(org.id, "sacco_credit_officer"), db,
        )
        assert assessed["assessment_status"] == "ineligible"
        assert assessed["status"] == "pending_assessment"
        with pytest.raises(HTTPException) as denied:
            decide_loan_application(
                application["id"], SaccoLoanDecisionIn(
                    decision="approve", note="Attempted approval"
                ), approver, _membership(org.id, "sacco_credit_approver"), db,
            )
        assert denied.value.status_code == 409
    finally:
        db.close()
        engine.dispose()


def test_loan_application_idempotency_and_tenant_branch_scope():
    from app.api.sacco_loans import create_loan_application, get_loan_application

    engine, db = _database()
    try:
        creator, manager, approver, org, borrower, guarantor = _seed(db, branch_id="branch-a")
        product = _create_product(db, manager, org)
        payload = _application_payload(borrower.id, product["id"])
        first = create_loan_application(
            payload, creator, _membership(org.id, "sacco_officer", "branch-a"), db
        )
        replay = create_loan_application(
            payload, creator, _membership(org.id, "sacco_officer", "branch-a"), db
        )
        assert first["id"] == replay["id"]
        with pytest.raises(HTTPException) as conflict:
            create_loan_application(
                _application_payload(borrower.id, product["id"], principal="11000.00"),
                creator, _membership(org.id, "sacco_officer", "branch-a"), db,
            )
        assert conflict.value.status_code == 409
        with pytest.raises(HTTPException) as branch_denied:
            get_loan_application(first["id"], _membership(org.id, "sacco_auditor", "branch-b"), db)
        assert branch_denied.value.status_code == 404
        other_org = Organization(name="Other SACCO", slug="other-sacco-loans")
        db.add(other_org)
        db.commit()
        with pytest.raises(HTTPException) as tenant_denied:
            get_loan_application(first["id"], _membership(other_org.id, "sacco_auditor"), db)
        assert tenant_denied.value.status_code == 404
    finally:
        db.close()
        engine.dispose()


def test_loan_product_currency_and_role_boundaries_are_enforced():
    from app.api.sacco_loans import create_loan_product

    engine, db = _database()
    try:
        creator, manager, approver, org, borrower, guarantor = _seed(db)
        with pytest.raises(HTTPException) as currency_denied:
            create_loan_product(
                _product_payload(currency="USD"), manager,
                _membership(org.id, "sacco_manager"), db,
            )
        assert currency_denied.value.status_code == 409
        with pytest.raises(HTTPException) as role_denied:
            create_loan_product(
                _product_payload(), creator, _membership(org.id, "sacco_officer"), db,
            )
        assert role_denied.value.status_code == 403
    finally:
        db.close()
        engine.dispose()


def test_loan_schedule_calculation_handles_zero_interest_and_month_end():
    from app.services.sacco_loans import monthly_installment, projected_schedule

    assert monthly_installment(Decimal("1200.00"), 0, 3) == Decimal("400.00")
    rows = projected_schedule(
        Decimal("1000.00"), 0, 3, date(2027, 1, 31)
    )
    assert [row["due_date"] for row in rows] == [
        date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31)
    ]
    assert sum((row["principal_due"] for row in rows), Decimal("0")) == Decimal("1000.00")
    assert rows[-1]["principal_due"] == Decimal("333.34")



def test_loan_disbursement_requires_independent_review_and_activates_schedule():
    from app.api.sacco_loans import (
        list_loan_disbursements, request_loan_disbursement,
        verify_loan_disbursement, get_loan_schedule,
    )

    engine, db = _database()
    try:
        creator, manager, approver, org, borrower, _ = _seed(db)
        product = _create_product(db, manager, org)
        application_out = _create_application(db, creator, org, borrower, product["id"])
        application = db.query(SaccoLoanApplication).filter_by(
            organization_id=org.id, id=application_out["id"]
        ).one()
        application.assessment_status = "eligible"
        application.assessed_by = manager.id
        application.assessed_at = datetime.now(timezone.utc)
        application.status = "approved_pending_disbursement"
        application.decided_by = approver.id
        application.decided_at = datetime.now(timezone.utc)
        application.decision_note = "Independent credit approval"
        db.add(SaccoLoanInstallment(
            organization_id=org.id, application_id=application.id,
            installment_number=1, due_date=application.first_repayment_date,
            principal_due=Decimal("10000.00"), interest_due=Decimal("0.00"),
            total_due=Decimal("10000.00"), currency="KES", status="projected",
        ))
        requester = User(
            email="loan-disbursement-requester@example.test",
            full_name="Disbursement Requester", password_hash="unused",
        )
        reviewer = User(
            email="loan-disbursement-reviewer@example.test",
            full_name="Disbursement Reviewer", password_hash="unused",
        )
        db.add_all([requester, reviewer])
        db.commit()

        payload = SaccoLoanDisbursementCreateIn(
            amount="10000.00", currency="KES", channel="bank_transfer",
            external_reference="BANK-STATEMENT-REF-001", value_date=date.today(),
            request_note="Bank statement settlement evidence attached to finance file",
            idempotency_key="loan-disbursement-001",
        )
        requester_membership = _membership(org.id, "sacco_manager")
        reviewer_membership = _membership(org.id, "sacco_treasurer")

        with pytest.raises(HTTPException) as creator_cannot_request:
            request_loan_disbursement(
                application.id, payload, creator, requester_membership, db
            )
        assert creator_cannot_request.value.status_code == 403

        with pytest.raises(HTTPException) as unauthorized:
            request_loan_disbursement(
                application.id, payload, requester, _membership(org.id, "sacco_officer"), db
            )
        assert unauthorized.value.status_code == 403

        with pytest.raises(HTTPException) as wrong_amount:
            request_loan_disbursement(
                application.id,
                payload.model_copy(update={"amount": Decimal("9000.00"), "idempotency_key": "loan-disbursement-002"}),
                requester, requester_membership, db,
            )
        assert wrong_amount.value.status_code == 422

        pending = request_loan_disbursement(
            application.id, payload, requester, requester_membership, db
        )
        assert pending["status"] == "pending_verification"
        replay = request_loan_disbursement(
            application.id, payload, requester, requester_membership, db
        )
        assert replay["id"] == pending["id"]

        with pytest.raises(HTTPException) as changed_replay:
            request_loan_disbursement(
                application.id,
                payload.model_copy(update={"external_reference": "DIFFERENT-REF"}),
                requester, requester_membership, db,
            )
        assert changed_replay.value.status_code == 409

        with pytest.raises(HTTPException) as duplicate_pending:
            request_loan_disbursement(
                application.id,
                payload.model_copy(update={"idempotency_key": "loan-disbursement-003"}),
                requester, requester_membership, db,
            )
        assert duplicate_pending.value.status_code == 409

        decision = SaccoLoanDisbursementVerificationIn(
            decision="verify", note="Bank statement and approved voucher independently checked"
        )
        with pytest.raises(HTTPException) as requester_cannot_review:
            verify_loan_disbursement(
                pending["id"], decision, requester, _membership(org.id, "org_admin"), db
            )
        assert requester_cannot_review.value.status_code == 403

        verified = verify_loan_disbursement(
            pending["id"], decision, reviewer, reviewer_membership, db
        )
        assert verified["status"] == "verified"
        db.refresh(application)
        assert application.status == "active"

        schedule = get_loan_schedule(
            application.id, _membership(org.id, "sacco_auditor"), db
        )
        assert schedule["schedule_type"] == "activated_after_staff_verified_disbursement"
        assert schedule["items"][0]["status"] == "projected"

        history = list_loan_disbursements(
            application.id, _membership(org.id, "sacco_auditor"), db
        )
        assert len(history["items"]) == 1
        assert history["items"][0]["external_reference"] == "BANK-STATEMENT-REF-001"

        events = db.query(AuditEvent).filter(
            AuditEvent.organization_id == org.id,
            AuditEvent.resource_type == "sacco_loan_disbursement",
        ).all()
        assert {event.action for event in events} >= {
            "sacco.loan_disbursement.requested", "sacco.loan_disbursement.verified"
        }
        with pytest.raises(HTTPException) as duplicate_verify:
            verify_loan_disbursement(
                pending["id"], decision, reviewer, reviewer_membership, db
            )
        assert duplicate_verify.value.status_code == 409
    finally:
        db.close()
        engine.dispose()


def test_rejected_loan_disbursement_can_be_resubmitted_without_duplicate_activation():
    from app.api.sacco_loans import request_loan_disbursement, verify_loan_disbursement

    engine, db = _database()
    try:
        creator, manager, approver, org, borrower, _ = _seed(db)
        product = _create_product(db, manager, org)
        application_out = _create_application(db, creator, org, borrower, product["id"])
        application = db.query(SaccoLoanApplication).filter_by(id=application_out["id"]).one()
        application.assessment_status = "eligible"
        application.assessed_by = manager.id
        application.assessed_at = datetime.now(timezone.utc)
        application.status = "approved_pending_disbursement"
        application.decided_by = approver.id
        application.decided_at = datetime.now(timezone.utc)
        requester = User(email="loan-retry-requester@example.test", full_name="Requester", password_hash="unused")
        reviewer = User(email="loan-retry-reviewer@example.test", full_name="Reviewer", password_hash="unused")
        db.add_all([requester, reviewer])
        db.commit()

        payload = SaccoLoanDisbursementCreateIn(
            amount="10000.00", currency="KES", channel="cash",
            external_reference="CASH-VOUCHER-001", value_date=date.today(),
            request_note="Cash voucher evidence recorded for independent review",
            idempotency_key="loan-retry-disbursement-001",
        )
        pending = request_loan_disbursement(
            application.id, payload, requester, _membership(org.id, "sacco_manager"), db
        )
        rejected = verify_loan_disbursement(
            pending["id"],
            SaccoLoanDisbursementVerificationIn(
                decision="reject", note="Voucher evidence does not reconcile to the approved amount"
            ),
            reviewer, _membership(org.id, "sacco_treasurer"), db,
        )
        assert rejected["status"] == "rejected"
        db.refresh(application)
        assert application.status == "approved_pending_disbursement"

        with pytest.raises(HTTPException) as reused_reference:
            request_loan_disbursement(
                application.id,
                SaccoLoanDisbursementCreateIn(
                    amount="10000.00", currency="KES", channel="cash",
                    external_reference="cash-voucher-001", value_date=date.today(),
                    request_note="Retry with the same external voucher reference",
                    idempotency_key="loan-retry-disbursement-reused",
                ),
                requester, _membership(org.id, "sacco_manager"), db,
            )
        assert reused_reference.value.status_code == 409

        replacement = request_loan_disbursement(
            application.id,
            payload.model_copy(update={
                "external_reference": "CASH-VOUCHER-002",
                "idempotency_key": "loan-retry-disbursement-002",
            }),
            requester, _membership(org.id, "sacco_manager"), db,
        )
        assert replacement["status"] == "pending_verification"
        assert replacement["id"] != pending["id"]
    finally:
        db.close()
        engine.dispose()


def test_sacco_loan_routes_migration_and_workspace_are_registered():
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/v1/sacco/loan-products" in paths
    assert "/api/v1/sacco/loan-applications" in paths
    assert "/api/v1/sacco/loan-applications/{application_id}/assessment" in paths
    assert "/api/v1/sacco/loan-applications/{application_id}/decision" in paths
    assert "/api/v1/sacco/loan-applications/{application_id}/disbursements" in paths
    assert "/api/v1/sacco/loan-disbursements/{disbursement_id}/verification" in paths
    root = Path(__file__).resolve().parents[1]
    migration = (root / "migrations" / "versions" / "0068_sacco_loan_origination.py").read_text(encoding="utf-8")
    assert 'revision = "0068_sacco_loan_origination"' in migration
    assert 'down_revision = "0067_sacco_member_ledger"' in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "REVOKE UPDATE, DELETE" in migration
    disbursement_migration = (root / "migrations" / "versions" / "0069_sacco_loan_disbursement.py").read_text(encoding="utf-8")
    assert 'revision = "0069_sacco_loan_disbursement"' in disbursement_migration
    assert 'down_revision = "0068_sacco_loan_origination"' in disbursement_migration
    assert "FORCE ROW LEVEL SECURITY" in disbursement_migration
    assert "uq_sacco_loan_disbursement_verified" in disbursement_migration
    page = (root / "app" / "web" / "sacco.html").read_text(encoding="utf-8")
    assert 'id="loanProduct"' in page and 'id="loanApplication"' in page
    assert 'id="loanDisbursement"' in page and 'id="loanDisbursementVerify"' in page
    assert "Powered by OneCore Technologies Ltd" in page
