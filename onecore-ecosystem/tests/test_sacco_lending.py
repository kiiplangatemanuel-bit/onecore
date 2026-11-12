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
from app.core.sacco_models import (
    SaccoMember, SaccoLoanProduct, SaccoLoanApplication, SaccoLoanLedgerEntry,
)
from app.core.sacco_schemas import (
    SaccoLoanProductCreateIn, SaccoLoanApplicationCreateIn, SaccoLoanAssessmentIn,
    SaccoLoanDecisionIn, SaccoLoanDisbursementIn, SaccoLoanRepaymentIn,
)
from app.services.sacco_lending import (
    calculate_flat_loan_terms, calculate_debt_service_ratio, allocate_repayment,
)


def _database():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[
        User.__table__, Organization.__table__, Membership.__table__, Branch.__table__,
        AuditEvent.__table__, SaccoMember.__table__, SaccoLoanProduct.__table__,
        SaccoLoanApplication.__table__, SaccoLoanLedgerEntry.__table__,
    ])
    return engine, Session(engine)


def _membership(organization_id, role, branch_scope="*"):
    return SimpleNamespace(organization_id=organization_id, role=role, branch_scope=branch_scope)


def _seed(db: Session, branch_id=None):
    applicant = User(email="loan-applicant@example.test", full_name="Applicant", password_hash="unused")
    assessor = User(email="loan-assessor@example.test", full_name="Assessor", password_hash="unused")
    approver = User(email="loan-approver@example.test", full_name="Approver", password_hash="unused")
    treasurer = User(email="loan-treasurer@example.test", full_name="Treasurer", password_hash="unused")
    manager = User(email="loan-manager@example.test", full_name="Manager", password_hash="unused")
    org = Organization(name="Loan SACCO", slug="loan-sacco", currency="KES")
    db.add_all([applicant, assessor, approver, treasurer, manager, org])
    db.flush()
    if branch_id:
        db.add(Branch(id=branch_id, organization_id=org.id, code="HQ", name="Head Office"))
        db.flush()
    member = SaccoMember(
        organization_id=org.id, branch_id=branch_id, member_number="MEM-LOAN-1",
        full_name="Jane Member", email=None, phone="+254700000001",
        identity_fingerprint="a" * 64, identity_ciphertext="encrypted-test",
        status="active", review_note="", reviewed_by=None, reviewed_at=None,
        created_by=applicant.id, idempotency_key="member-loan-create-1",
        request_fingerprint="b" * 64,
    )
    db.add(member)
    db.commit()
    return applicant, assessor, approver, treasurer, manager, org, member


def _product_payload(**overrides):
    values = {
        "code": "development", "name": "Development Loan",
        "min_amount": "1000.00", "max_amount": "100000.00",
        "annual_interest_rate": "12.0000", "min_term_months": 3,
        "max_term_months": 24, "max_debt_service_ratio": "0.4000",
    }
    values.update(overrides)
    return SaccoLoanProductCreateIn(**values)


def _application_payload(product_id, **overrides):
    values = {
        "product_id": product_id, "requested_amount": "12000.00",
        "term_months": 12, "purpose": "Purchase business equipment",
        "idempotency_key": "loan-application-key-0001",
    }
    values.update(overrides)
    return SaccoLoanApplicationCreateIn(**values)


def _assessment(**overrides):
    values = {
        "monthly_net_income": "10000.00", "existing_monthly_debt": "1000.00",
        "note": "Payslip and existing obligations reviewed",
    }
    values.update(overrides)
    return SaccoLoanAssessmentIn(**values)


def test_flat_interest_and_repayment_allocation_are_decimal_and_deterministic():
    interest, total, installment = calculate_flat_loan_terms(
        Decimal("12000.00"), Decimal("12.0000"), 12
    )
    assert interest == Decimal("1440.00")
    assert total == Decimal("13440.00")
    assert installment == Decimal("1120.00")
    assert calculate_debt_service_ratio(
        Decimal("10000.00"), Decimal("1000.00"), installment
    ) == Decimal("0.2120")
    principal_delta, interest_delta = allocate_repayment(
        Decimal("1000.00"), Decimal("12000.00"), Decimal("1440.00")
    )
    assert principal_delta == Decimal("0.00")
    assert interest_delta == Decimal("-1000.00")
    with pytest.raises(ValueError):
        allocate_repayment(Decimal("13440.01"), Decimal("12000.00"), Decimal("1440.00"))


def test_loan_contracts_enforce_product_and_application_limits():
    assert _product_payload().code == "DEVELOPMENT"
    with pytest.raises(ValidationError):
        _product_payload(min_amount="5000.00", max_amount="1000.00")
    with pytest.raises(ValidationError):
        _product_payload(max_term_months=2)
    with pytest.raises(ValidationError):
        _application_payload(1, requested_amount="0.00")
    with pytest.raises(ValidationError):
        _assessment(monthly_net_income="0.00")


def test_loan_product_application_underwriting_four_eyes_disbursement_and_repayment():
    from app.api.sacco import (
        create_loan_product, create_loan_application, assess_loan_application,
        decide_loan_application, disburse_loan_application, repay_loan_application,
        get_loan_ledger,
    )

    engine, db = _database()
    try:
        applicant, assessor, approver, treasurer, manager, org, member = _seed(db)
        manager_role = _membership(org.id, "sacco_manager")
        applicant_role = _membership(org.id, "sacco_officer")
        assessor_role = _membership(org.id, "sacco_credit_officer")
        approver_role = _membership(org.id, "sacco_credit_approver")
        treasurer_role = _membership(org.id, "sacco_treasurer")

        product = create_loan_product(_product_payload(), manager, manager_role, db)
        assert product["currency"] == "KES" and product["is_active"] is True
        application_payload = _application_payload(product["id"])
        application = create_loan_application(member.id, application_payload, applicant, applicant_role, db)
        assert application["status"] == "submitted" and application["replayed"] is False
        replay = create_loan_application(member.id, application_payload, applicant, applicant_role, db)
        assert replay["id"] == application["id"] and replay["replayed"] is True

        with pytest.raises(HTTPException) as creator_assess:
            assess_loan_application(application["id"], _assessment(), applicant, assessor_role, db)
        assert creator_assess.value.status_code == 403
        assessed = assess_loan_application(
            application["id"], _assessment(), assessor, assessor_role, db
        )
        assert assessed["status"] == "assessed"
        assert assessed["assessment_recommendation"] == "approve"
        assert assessed["assessment_monthly_installment"] == "1120.00"
        assert assessed["assessment_total_interest"] == "1440.00"
        assert assessed["assessment_debt_service_ratio"] == "0.2120"

        with pytest.raises(HTTPException) as applicant_decides:
            decide_loan_application(
                application["id"], SaccoLoanDecisionIn(decision="approve", note="Approved after review"),
                applicant, approver_role, db,
            )
        assert applicant_decides.value.status_code == 403
        with pytest.raises(HTTPException) as assessor_decides:
            decide_loan_application(
                application["id"], SaccoLoanDecisionIn(decision="approve", note="Approved after review"),
                assessor, approver_role, db,
            )
        assert assessor_decides.value.status_code == 403
        approved = decide_loan_application(
            application["id"], SaccoLoanDecisionIn(decision="approve", note="Independent credit approval"),
            approver, approver_role, db,
        )
        assert approved["status"] == "approved" and approved["decision_by"] == approver.id

        with pytest.raises(HTTPException) as approver_disburses:
            disburse_loan_application(
                application["id"], SaccoLoanDisbursementIn(reference="cashbook-001", idempotency_key="loan-disburse-001"),
                approver, approver_role, db,
            )
        assert approver_disburses.value.status_code == 403
        disbursement_payload = SaccoLoanDisbursementIn(
            reference="cashbook-001", idempotency_key="loan-disburse-001"
        )
        disbursement = disburse_loan_application(
            application["id"], disbursement_payload, treasurer, treasurer_role, db
        )
        assert disbursement["entry_type"] == "disbursement"
        assert disbursement["principal_delta"] == "12000.00"
        assert disbursement["interest_delta"] == "1440.00"
        replay_disbursement = disburse_loan_application(
            application["id"], disbursement_payload, treasurer, treasurer_role, db
        )
        assert replay_disbursement["replayed"] is True

        first_repayment_payload = SaccoLoanRepaymentIn(
            amount="1000.00", reference="receipt-001", idempotency_key="loan-repay-0001"
        )
        first_repayment = repay_loan_application(
            application["id"], first_repayment_payload, treasurer, treasurer_role, db
        )
        assert first_repayment["principal_delta"] == "0.00"
        assert first_repayment["interest_delta"] == "-1000.00"
        replay_repayment = repay_loan_application(
            application["id"], first_repayment_payload, treasurer, treasurer_role, db
        )
        assert replay_repayment["replayed"] is True

        second = repay_loan_application(
            application["id"],
            SaccoLoanRepaymentIn(amount="5000.00", reference="receipt-002", idempotency_key="loan-repay-0002"),
            treasurer, treasurer_role, db,
        )
        assert second["principal_delta"] == "-4560.00"
        assert second["interest_delta"] == "-440.00"
        balance = get_loan_ledger(application["id"], treasurer_role, db)
        assert balance["principal_outstanding"] == "7440.00"
        assert balance["interest_outstanding"] == "0.00"
        assert balance["total_outstanding"] == "7440.00"

        with pytest.raises(HTTPException) as overpayment:
            repay_loan_application(
                application["id"],
                SaccoLoanRepaymentIn(amount="7440.01", reference="too-much", idempotency_key="loan-repay-0003"),
                treasurer, treasurer_role, db,
            )
        assert overpayment.value.status_code == 409
        final = repay_loan_application(
            application["id"],
            SaccoLoanRepaymentIn(amount="7440.00", reference="receipt-final", idempotency_key="loan-repay-0004"),
            treasurer, treasurer_role, db,
        )
        assert final["principal_delta"] == "-7440.00"
        closed = get_loan_ledger(application["id"], treasurer_role, db)
        assert closed["loan_application"]["status"] == "closed"
        assert closed["total_outstanding"] == "0.00"
        assert db.query(SaccoLoanLedgerEntry).filter_by(loan_application_id=application["id"]).count() == 4
        assert db.query(AuditEvent).filter(AuditEvent.action.like("sacco.loan_application.%")).count() == 6
    finally:
        db.close()
        engine.dispose()


def test_affordability_decline_cannot_be_overridden_by_approval():
    from app.api.sacco import create_loan_product, create_loan_application, assess_loan_application, decide_loan_application

    engine, db = _database()
    try:
        applicant, assessor, approver, treasurer, manager, org, member = _seed(db)
        manager_role = _membership(org.id, "sacco_manager")
        applicant_role = _membership(org.id, "sacco_officer")
        assessor_role = _membership(org.id, "sacco_credit_officer")
        approver_role = _membership(org.id, "sacco_credit_approver")
        product = create_loan_product(_product_payload(code="SMALL", max_debt_service_ratio="0.3000"), manager, manager_role, db)
        application = create_loan_application(
            member.id, _application_payload(product["id"], idempotency_key="loan-decline-0001"),
            applicant, applicant_role, db,
        )
        assessed = assess_loan_application(
            application["id"],
            _assessment(monthly_net_income="1000.00", existing_monthly_debt="500.00"),
            assessor, assessor_role, db,
        )
        assert assessed["assessment_recommendation"] == "decline"
        with pytest.raises(HTTPException) as rejected:
            decide_loan_application(
                application["id"], SaccoLoanDecisionIn(decision="approve", note="Attempted override"),
                approver, approver_role, db,
            )
        assert rejected.value.status_code == 409
        result = decide_loan_application(
            application["id"], SaccoLoanDecisionIn(decision="reject", note="Affordability threshold exceeded"),
            approver, approver_role, db,
        )
        assert result["status"] == "rejected"
    finally:
        db.close()
        engine.dispose()


def test_tenant_and_branch_scope_hide_loan_applications():
    from app.api.sacco import create_loan_product, create_loan_application, get_loan_application

    engine, db = _database()
    try:
        applicant, assessor, approver, treasurer, manager, org, member = _seed(db, branch_id="branch-a")
        manager_role = _membership(org.id, "sacco_manager")
        applicant_role = _membership(org.id, "sacco_officer")
        product = create_loan_product(_product_payload(), manager, manager_role, db)
        application = create_loan_application(
            member.id, _application_payload(product["id"]), applicant, applicant_role, db
        )
        restricted = _membership(org.id, "sacco_auditor", "branch-b")
        with pytest.raises(HTTPException) as branch_denied:
            get_loan_application(application["id"], restricted, db)
        assert branch_denied.value.status_code == 404
        other = Organization(name="Other loan tenant", slug="other-loan-tenant")
        db.add(other)
        db.commit()
        with pytest.raises(HTTPException) as tenant_denied:
            get_loan_application(application["id"], _membership(other.id, "sacco_auditor"), db)
        assert tenant_denied.value.status_code == 404
    finally:
        db.close()
        engine.dispose()


def test_sacco_lending_models_routes_migration_roles_and_workspace_contract():
    from app.main import app
    from app.api.platform_routes import InvitationIn

    assert SaccoLoanProduct.__tablename__ == "sacco_loan_products"
    assert SaccoLoanApplication.__tablename__ == "sacco_loan_applications"
    assert SaccoLoanLedgerEntry.__tablename__ == "sacco_loan_ledger_entries"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/sacco/loan-products" in paths
    assert "/api/v1/sacco/loan-applications" in paths
    assert "/api/v1/sacco/loan-applications/{loan_id}/assessment" in paths
    assert "/api/v1/sacco/loan-applications/{loan_id}/decision" in paths
    assert "/api/v1/sacco/loan-applications/{loan_id}/disbursement" in paths
    assert "/api/v1/sacco/loan-applications/{loan_id}/repayments" in paths
    for role in ("sacco_credit_officer", "sacco_credit_approver"):
        assert InvitationIn(email="credit@example.test", role=role).role == role

    migration = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0068_sacco_lending_workflow.py"
    source = migration.read_text(encoding="utf-8")
    assert 'revision = "0068_sacco_lending_workflow"' in source
    assert 'down_revision = "0067_sacco_member_ledger"' in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "trg_sacco_loan_ledger_entries_immutable" in source
    assert "GRANT UPDATE (" in source

    page = Path(__file__).resolve().parents[1] / "app" / "web" / "sacco.html"
    html = page.read_text(encoding="utf-8")
    assert 'id="loanProduct"' in html
    assert 'id="loanApplication"' in html
    assert 'id="loanAssessment"' in html
    assert 'id="loanDecision"' in html
    assert 'id="loanDisbursement"' in html
    assert 'id="loanRepayment"' in html
    assert "Powered by OneCore Technologies Ltd" in html
