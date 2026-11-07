from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.models import (
    SaccoMember, SaccoAccount, SaccoTransaction, SaccoLoanProduct, SaccoLoanApplication,
)
from app.core.schemas import (
    SaccoMemberIn, SaccoKYCDecisionIn, SaccoAccountIn, SaccoTransactionIn,
    SaccoLoanProductIn, SaccoLoanApplicationIn, SaccoLoanDecisionIn,
)
from app.main import app


def test_sacco_models_and_tenant_idempotency_indexes():
    assert SaccoMember.__tablename__ == "sacco_members"
    assert SaccoAccount.__tablename__ == "sacco_accounts"
    assert SaccoTransaction.__tablename__ == "sacco_transactions"
    assert SaccoLoanProduct.__tablename__ == "sacco_loan_products"
    assert SaccoLoanApplication.__tablename__ == "sacco_loan_applications"
    indexes = {item.name for item in SaccoTransaction.__table__.indexes}
    assert "ix_sacco_transaction_org_idempotency" in indexes
    assert "ix_sacco_member_org_number" in {item.name for item in SaccoMember.__table__.indexes}


def test_sacco_member_and_kyc_contracts_normalize_and_validate():
    member = SaccoMemberIn(member_number=" MEM-001 ", full_name="  Jane Member  ")
    assert member.full_name == "Jane Member"
    assert member.member_number == " MEM-001 "
    decision = SaccoKYCDecisionIn(decision="verified", note="Documents checked")
    assert decision.decision == "verified"
    with pytest.raises(ValidationError):
        SaccoKYCDecisionIn(decision="pending", note="No")


def test_sacco_account_transaction_contracts():
    account = SaccoAccountIn(member_id=1, account_type="savings", currency="KES")
    assert account.account_type == "savings"
    transaction = SaccoTransactionIn(
        transaction_type="deposit", amount=Decimal("100.00"),
        reference="cash desk", idempotency_key="cash-deposit-001",
    )
    assert transaction.amount == Decimal("100.00")
    with pytest.raises(ValidationError):
        SaccoTransactionIn(
            transaction_type="withdrawal", amount=Decimal("0"),
            idempotency_key="bad-amount",
        )
    with pytest.raises(ValidationError):
        SaccoTransactionIn(
            transaction_type="deposit", amount=Decimal("1.001"),
            idempotency_key="bad-precision",
        )


def test_sacco_loan_product_and_application_contracts():
    product = SaccoLoanProductIn(
        code="DEV", name="Development Loan",
        minimum_principal=Decimal("1000"), maximum_principal=Decimal("100000"),
        annual_interest_rate=Decimal("12.0000"), minimum_term_months=3,
        maximum_term_months=36, interest_method="reducing",
    )
    assert product.maximum_principal >= product.minimum_principal
    with pytest.raises(ValidationError):
        SaccoLoanProductIn(
            code="BAD", name="Invalid Loan",
            minimum_principal=Decimal("10000"), maximum_principal=Decimal("1000"),
            annual_interest_rate=Decimal("12"), minimum_term_months=12,
            maximum_term_months=6,
        )
    application = SaccoLoanApplicationIn(
        member_id=1, loan_product_id=1, requested_principal=Decimal("5000.00"),
        term_months=12, purpose="Purchase farm inputs",
    )
    assert application.term_months == 12
    with pytest.raises(ValidationError):
        SaccoLoanDecisionIn(decision="defer", note="Review later")


def test_sacco_api_routes_are_registered():
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/v1/sacco/members",
        "/api/v1/sacco/members/{member_id}/kyc-decision",
        "/api/v1/sacco/accounts",
        "/api/v1/sacco/accounts/{account_id}/transactions",
        "/api/v1/sacco/loan-products",
        "/api/v1/sacco/loan-applications",
        "/api/v1/sacco/loan-applications/{application_id}/decision",
        "/sacco",
    }
    assert expected <= paths
