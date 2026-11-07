from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.schemas import SaccoLoanDisbursementIn, SaccoLoanRepaymentIn
from app.services.sacco import add_months, allocate_repayment, build_repayment_schedule
from app.main import app


def test_flat_schedule_reconciles_principal_and_interest():
    rows = build_repayment_schedule(
        Decimal("12000.00"), Decimal("12.0000"), 12, "flat", date(2026, 2, 28)
    )
    assert len(rows) == 12
    assert sum((row["principal_due"] for row in rows), Decimal("0.00")) == Decimal("12000.00")
    assert sum((row["interest_due"] for row in rows), Decimal("0.00")) == Decimal("1440.00")
    assert rows[0]["due_date"] == date(2026, 2, 28)
    assert rows[-1]["due_date"] == date(2027, 1, 28)


def test_reducing_schedule_amortizes_principal_and_interest():
    rows = build_repayment_schedule(
        Decimal("12000.00"), Decimal("12.0000"), 12, "reducing", date(2026, 2, 28)
    )
    assert len(rows) == 12
    assert sum((row["principal_due"] for row in rows), Decimal("0.00")) == Decimal("12000.00")
    assert sum((row["interest_due"] for row in rows), Decimal("0.00")) > 0
    assert rows[-1]["principal_due"] > 0


def test_zero_interest_schedule_and_month_end_dates():
    rows = build_repayment_schedule(
        Decimal("100.00"), Decimal("0"), 3, "reducing", date(2026, 1, 31)
    )
    assert [row["due_date"] for row in rows] == [
        date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)
    ]
    assert sum((row["principal_due"] for row in rows), Decimal("0.00")) == Decimal("100.00")
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_repayment_allocation_pays_interest_before_principal():
    row = SimpleNamespace(
        interest_due=Decimal("10.00"), interest_paid=Decimal("0.00"),
        principal_due=Decimal("100.00"), principal_paid=Decimal("0.00"),
    )
    principal, interest, allocations = allocate_repayment(Decimal("15.00"), [row])
    assert interest == Decimal("10.00")
    assert principal == Decimal("5.00")
    assert allocations == [(row, Decimal("10.00"), Decimal("5.00"))]


def test_repayment_allocation_rejects_overpayment():
    row = SimpleNamespace(
        interest_due=Decimal("10.00"), interest_paid=Decimal("0.00"),
        principal_due=Decimal("100.00"), principal_paid=Decimal("0.00"),
    )
    with pytest.raises(ValueError):
        allocate_repayment(Decimal("111.00"), [row])


def test_loan_servicing_contracts_and_routes():
    assert SaccoLoanDisbursementIn(reference="bank instruction ref").reference == "bank instruction ref"
    assert SaccoLoanRepaymentIn(
        amount=Decimal("500.00"), idempotency_key="repayment-0001"
    ).amount == Decimal("500.00")
    with pytest.raises(ValidationError):
        SaccoLoanRepaymentIn(amount=Decimal("1.001"), idempotency_key="bad-precision")
    paths = set(app.openapi()["paths"])
    assert "/api/v1/sacco/loan-applications/{application_id}/disburse" in paths
    assert "/api/v1/sacco/loans" in paths
    assert "/api/v1/sacco/loans/{loan_id}/schedule" in paths
    assert "/api/v1/sacco/loans/{loan_id}/repayments" in paths


def test_sacco_arrears_ageing_route_contract_and_scope():
    paths = app.openapi()["paths"]
    endpoint = "/api/v1/sacco/loans/arrears"
    assert endpoint in paths
    params = {item["name"] for item in paths[endpoint]["get"]["parameters"]}
    assert "as_of" in params


def test_sacco_arrears_ageing_ui_is_read_only():
    from pathlib import Path
    page = Path(__file__).resolve().parents[1] / "app" / "web" / "sacco.html"
    html = page.read_text(encoding="utf-8")
    assert 'id="arrearsForm"' in html
    assert 'id="arrearsRows"' in html
    assert "/sacco/loans/arrears" in html
    assert "No late fees or penalties are calculated or posted" in html



def test_sacco_guarantor_and_collateral_contracts():
    from app.core.schemas import (SaccoLoanGuarantorIn, SaccoLoanCollateralIn,
        SaccoLoanGuarantorDecisionIn, SaccoLoanCollateralDecisionIn)
    assert SaccoLoanGuarantorIn(member_id=2, guaranteed_amount=Decimal("500.00"),
        consent_reference="CONSENT-001").member_id == 2
    assert SaccoLoanCollateralIn(collateral_type="vehicle", description="Motor vehicle",
        owner_name="Member Name", estimated_value=Decimal("120000.00")).estimated_value == Decimal("120000.00")
    with pytest.raises(ValidationError):
        SaccoLoanGuarantorIn(member_id=2, guaranteed_amount=Decimal("1.001"),
            consent_reference="CONSENT-001")
    with pytest.raises(ValidationError):
        SaccoLoanCollateralDecisionIn(decision="accepted", note="Accepted")
    paths = set(app.openapi()["paths"])
    assert "/api/v1/sacco/loans/{loan_id}/guarantors" in paths
    assert "/api/v1/sacco/loans/{loan_id}/guarantors/{guarantor_id}/decision" in paths
    assert "/api/v1/sacco/loans/{loan_id}/collateral" in paths
    assert "/api/v1/sacco/loans/{loan_id}/collateral/{collateral_id}/decision" in paths
