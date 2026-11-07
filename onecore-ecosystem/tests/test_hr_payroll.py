from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.models import HRPayrollProfile, HRPayrollRun, HRPayrollLine, HRPayrollItem
from app.core.schemas import HRPayrollProfileIn, HRPayrollRunIn, HRPayrollItemIn
from app.services.hr import payroll_item_hash, payroll_money, payroll_totals
from app.main import app


def test_payroll_profile_contract_and_effective_dates():
    profile = HRPayrollProfileIn(
        employee_id=4, currency="KES", base_period_pay="85000.00",
        effective_from=date(2026, 11, 1), effective_to=date(2027, 10, 31),
    )
    assert profile.base_period_pay == Decimal("85000.00")
    with pytest.raises(ValidationError):
        HRPayrollProfileIn(employee_id=4, currency="KES", base_period_pay="0",
                           effective_from=date(2026, 11, 1))
    with pytest.raises(ValidationError):
        HRPayrollProfileIn(employee_id=4, currency="KES", base_period_pay="85000",
                           effective_from=date(2026, 11, 2), effective_to=date(2026, 11, 1))


def test_payroll_run_period_contract():
    run = HRPayrollRunIn(
        period_start=date(2026, 11, 1), period_end=date(2026, 11, 30),
        pay_date=date(2026, 12, 1),
    )
    assert run.period_end.day == 30
    with pytest.raises(ValidationError):
        HRPayrollRunIn(period_start=date(2026, 11, 30), period_end=date(2026, 11, 1),
                       pay_date=date(2026, 12, 1))
    with pytest.raises(ValidationError):
        HRPayrollRunIn(period_start=date(2026, 11, 1), period_end=date(2026, 11, 30),
                       pay_date=date(2026, 11, 29))


def test_payroll_item_requires_positive_money_and_known_type():
    item = HRPayrollItemIn(
        client_item_id="payroll-item-0001", employee_id=4, item_type="earning",
        code="OVERTIME", description="Approved overtime", amount="2500.00",
    )
    assert item.amount == Decimal("2500.00")
    with pytest.raises(ValidationError):
        HRPayrollItemIn(client_item_id="payroll-item-0002", employee_id=4,
                        item_type="tax", code="TAX", description="Tax", amount="10.00")
    with pytest.raises(ValidationError):
        HRPayrollItemIn(client_item_id="payroll-item-0003", employee_id=4,
                        item_type="earning", code="BONUS", description="Bonus", amount="0")


def test_payroll_calculations_are_decimal_and_deductions_cannot_exceed_gross():
    items = [
        SimpleNamespace(item_type="earning", amount=Decimal("10000.00")),
        SimpleNamespace(item_type="deduction", amount=Decimal("5000.00")),
    ]
    gross, deductions, net = payroll_totals(Decimal("85000.00"), items)
    assert (gross, deductions, net) == (
        Decimal("95000.00"), Decimal("5000.00"), Decimal("90000.00")
    )
    with pytest.raises(ValueError):
        payroll_totals(Decimal("100.00"), [
            SimpleNamespace(item_type="deduction", amount=Decimal("101.00"))
        ])
    assert payroll_money("10.125") == Decimal("10.13")


def test_payroll_item_idempotency_hash_is_canonical():
    first = HRPayrollItemIn(
        client_item_id="payroll-item-0004", employee_id=4, item_type="earning",
        code="bonus", description="Performance bonus", amount="100.00",
    )
    second = HRPayrollItemIn(
        client_item_id="payroll-item-0004", employee_id=4, item_type="earning",
        code="BONUS", description="Performance bonus", amount="100.00",
    )
    assert payroll_item_hash(first) == payroll_item_hash(second)


def test_payroll_models_and_api_contracts_are_registered():
    assert HRPayrollProfile.__tablename__ == "hr_payroll_profiles"
    assert HRPayrollRun.__tablename__ == "hr_payroll_runs"
    assert HRPayrollLine.__tablename__ == "hr_payroll_lines"
    assert HRPayrollItem.__tablename__ == "hr_payroll_items"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/hr/payroll/profiles" in paths
    assert "/api/v1/hr/payroll/runs" in paths
    assert "/api/v1/hr/payroll/runs/{run_id}/items" in paths
    assert "/api/v1/hr/payroll/runs/{run_id}/approve" in paths
    assert "/api/v1/hr/payroll/my-payslips" in paths
