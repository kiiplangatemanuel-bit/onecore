from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from types import SimpleNamespace
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.hr_payroll import (
    LeaveIn, PayrollRunIn, RuleSetIn, HRShiftIn, AttendanceIn, _calculate, _progressive_tax, _tiered_contribution, require_payroll_action,
)
from app.core.hr_payroll_models import HREmployee, HRLeaveRequest, PayrollRuleSet, PayrollRun, PayrollPayslip, PayrollAccountingMapping, PayrollAccountingLink, HRShift, HRAttendance
from app.main import app


def evidence(authority, url):
    return {"authority": authority, "url": url, "title": authority + " official rates",
            "effective_date": "2026-01-01", "checked_on": "2026-11-08"}


def valid_rules(**overrides):
    values = {
        "effective_from": date(2026, 1, 1),
        "paye_bands": [
            {"lower_bound": "0", "upper_bound": "10000", "rate": "0.1"},
            {"lower_bound": "10000", "upper_bound": None, "rate": "0.2"},
        ],
        "personal_relief": "1000",
        "pension_tax_deductible_limit": "3000",
        "nssf_tiers": [
            {"lower_bound": "0", "upper_bound": "1000", "employee_rate": "0.06", "employer_rate": "0.06"},
            {"lower_bound": "1000", "upper_bound": "2000", "employee_rate": "0.06", "employer_rate": "0.06"},
        ],
        "shif_rate": "0.0275",
        "housing_levy_employee_rate": "0.015",
        "housing_levy_employer_rate": "0.015",
        "source_evidence": [
            evidence("KRA", "https://www.kra.go.ke/"),
            evidence("NSSF", "https://www.nssf.or.ke/"),
            evidence("SHA", "https://sha.go.ke/"),
        ],
    }
    values.update(overrides)
    return values


def test_hr_payroll_domain_models_are_tenant_scoped_and_snapshotted():
    assert HREmployee.__tablename__ == "hr_employees"
    assert HRLeaveRequest.__tablename__ == "hr_leave_requests"
    assert PayrollRuleSet.__tablename__ == "payroll_rule_sets"
    assert PayrollRun.__tablename__ == "payroll_runs"
    assert PayrollPayslip.__tablename__ == "payroll_payslips"
    assert PayrollAccountingMapping.__tablename__ == "payroll_accounting_mappings"
    assert PayrollAccountingLink.__tablename__ == "payroll_accounting_links"
    assert HRShift.__tablename__ == "hr_shifts"
    assert HRAttendance.__tablename__ == "hr_attendance"
    assert "uq_payroll_run_org_idempotency" in {x.name for x in PayrollRun.__table__.indexes}
    assert "uq_payroll_payslip_run_employee" in {x.name for x in PayrollPayslip.__table__.indexes}


def test_hr_payroll_routes_are_registered():
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/hr/employees", "/api/v1/hr/employees/{employee_id}/employment-status",
        "/api/v1/hr/employees/{employee_id}/leave", "/api/v1/hr/shifts",
        "/api/v1/hr/attendance", "/api/v1/hr/attendance/{attendance_id}/decision",
        "/api/v1/hr/leave-requests", "/api/v1/hr/leave-requests/{request_id}/decision",
        "/api/v1/payroll/rule-sets", "/api/v1/payroll/rule-sets/{rule_set_id}/submit",
        "/api/v1/payroll/rule-sets/{rule_set_id}/approve", "/api/v1/payroll/runs",
        "/api/v1/payroll/runs/{run_id}/submit", "/api/v1/payroll/runs/{run_id}/approve",
        "/api/v1/payroll/runs/{run_id}/mark-paid", "/api/v1/payroll/runs/{run_id}/payslips",
        "/api/v1/payroll/accounting-mapping", "/api/v1/payroll/runs/{run_id}/post-to-accounting",
        "/api/v1/payroll/runs/{run_id}/reverse-accounting-journal",
    }
    assert expected.issubset(paths)


def test_leave_request_requires_valid_dates_and_positive_days():
    request = LeaveIn(leave_type="annual", start_date="2026-11-10",
                      end_date="2026-11-12", days="3", reason="Annual leave")
    assert request.days == Decimal("3")
    with pytest.raises(ValidationError):
        LeaveIn(leave_type="annual", start_date="2026-11-12",
                end_date="2026-11-10", days="3")
    with pytest.raises(ValidationError):
        LeaveIn(leave_type="unknown", start_date="2026-11-10",
                end_date="2026-11-12", days="0")


def test_statutory_rule_sets_require_official_evidence_and_valid_bands():
    payload = RuleSetIn(**valid_rules())
    assert len(payload.paye_bands) == 2
    with pytest.raises(ValidationError):
        RuleSetIn(**valid_rules(source_evidence=[
            evidence("KRA", "https://example.com/"),
            evidence("NSSF", "https://www.nssf.or.ke/"),
            evidence("SHA", "https://sha.go.ke/"),
        ]))
    with pytest.raises(ValidationError):
        RuleSetIn(**valid_rules(paye_bands=[{"lower_bound": "0", "upper_bound": "10000", "rate": "0.1"}]))
    with pytest.raises(ValidationError):
        RuleSetIn(**valid_rules(paye_bands=[
            {"lower_bound": "0", "upper_bound": "10000", "rate": "0.1"},
            {"lower_bound": "9000", "upper_bound": None, "rate": "0.2"},
        ]))
    with pytest.raises(ValidationError):
        RuleSetIn(**valid_rules(nssf_tiers=[
            {"lower_bound": "0", "upper_bound": "1000", "employee_rate": "0.06", "employer_rate": "0.06"},
            {"lower_bound": "900", "upper_bound": "2000", "employee_rate": "0.06", "employer_rate": "0.06"},
        ]))


def test_payroll_calculation_uses_versioned_configured_rates_and_cent_rounding():
    employee = HREmployee(
        id=7, organization_id=1, employee_number="EMP-007",
        first_name="Ada", last_name="Learner", hire_date=datetime(2026, 1, 1, tzinfo=timezone.utc), base_salary=Decimal("20000.00"),
        recurring_allowances={"transport": "1000.00"}, recurring_benefits={"housing": "500.00"},
        pension_contribution=Decimal("1000.00"),
    )
    rules = {
        "paye_bands": [
            {"lower_bound": "0", "upper_bound": "10000", "rate": "0.1"},
            {"lower_bound": "10000", "upper_bound": None, "rate": "0.2"},
        ],
        "personal_relief": "1000",
        "pension_tax_deductible_limit": "3000",
        "nssf_tiers": [
            {"lower_bound": "0", "upper_bound": "1000", "employee_rate": "0.06", "employer_rate": "0.06"},
            {"lower_bound": "1000", "upper_bound": "2000", "employee_rate": "0.06", "employer_rate": "0.06"},
        ],
        "shif_rate": "0.0275",
        "housing_levy_employee_rate": "0.015",
        "housing_levy_employer_rate": "0.015",
    }
    result = _calculate(employee, rules, date(2026, 1, 1), date(2026, 1, 31))
    assert result["gross_pay"] == "21500.00"
    assert result["proration_days"] == 31
    assert result["period_days"] == 31
    employee.hire_date = datetime(2026, 1, 16, tzinfo=timezone.utc)
    prorated = _calculate(employee, rules, date(2026, 1, 1), date(2026, 1, 31))
    assert prorated["proration_days"] == 16
    assert prorated["gross_pay"] == "11096.77"
    assert result["taxable_pay"] == "20500.00"
    assert result["nssf_employee"] == "120.00"
    assert result["nssf_employer"] == "120.00"
    assert result["shif_employee"] == "591.25"
    assert result["housing_levy_employee"] == "322.50"
    assert result["housing_levy_employer"] == "322.50"
    assert result["net_pay"] == "17366.25"
    assert _progressive_tax(Decimal("15000"), rules["paye_bands"]) == Decimal("2000.00")
    assert _tiered_contribution(Decimal("1500"), rules["nssf_tiers"], "employee_rate") == Decimal("90.00")


def test_hr_payroll_authorization_supports_maker_checker_roles():
    from app.core.authorization import ROLE_PERMISSIONS
    assert "manage" in ROLE_PERMISSIONS["org_admin"]
    assert "manage" not in ROLE_PERMISSIONS["accountant"]
    assert "manage" not in ROLE_PERMISSIONS["payroll_manager"]
    assert "manage" not in ROLE_PERMISSIONS["payroll_approver"]
    assert "manage" not in ROLE_PERMISSIONS["payroll_payment"]
    assert "create" not in ROLE_PERMISSIONS["payroll_manager"]
    assert "create" not in ROLE_PERMISSIONS["hr_manager"]
    assert "create" not in ROLE_PERMISSIONS["payroll_approver"]
    assert ROLE_PERMISSIONS["payroll_accounting"] == {"read"}



def test_payroll_run_requires_full_calendar_month_and_unique_employee_ids():
    payload = PayrollRunIn(period_start="2026-02-01", period_end="2026-02-28",
                           employee_ids=[1, 2], idempotency_key="payroll-feb-2026")
    assert payload.period_end == date(2026, 2, 28)
    with pytest.raises(ValidationError):
        PayrollRunIn(period_start="2026-02-01", period_end="2026-02-27",
                     employee_ids=[1], idempotency_key="payroll-feb-2026")
    with pytest.raises(ValidationError):
        PayrollRunIn(period_start="2026-02-01", period_end="2026-02-28",
                     employee_ids=[1, 1], idempotency_key="payroll-feb-2026")


def test_payroll_actions_are_separated_by_role():
    require_payroll_action(SimpleNamespace(role="payroll_manager"), "prepare")
    require_payroll_action(SimpleNamespace(role="payroll_approver"), "approve")
    require_payroll_action(SimpleNamespace(role="payroll_payment"), "pay")
    with pytest.raises(HTTPException):
        require_payroll_action(SimpleNamespace(role="payroll_manager"), "approve")
    with pytest.raises(HTTPException):
        require_payroll_action(SimpleNamespace(role="payroll_approver"), "prepare")
    with pytest.raises(HTTPException):
        require_payroll_action(SimpleNamespace(role="payroll_payment"), "prepare")



def test_shift_and_attendance_inputs_validate_schedule_and_clock_times():
    shift = HRShiftIn(shift_code="DAY", name="Day shift", start_time="08:00",
                      end_time="17:00", break_minutes=60, differential_rate="0.10")
    assert shift.differential_rate == Decimal("0.10")
    with pytest.raises(ValidationError):
        HRShiftIn(shift_code="BAD", name="Invalid shift", start_time="08:00",
                  end_time="09:00", break_minutes=60)
    attendance = AttendanceIn(employee_id=1, shift_id=1, attendance_date="2026-11-01",
        clock_in="2026-11-01T08:00:00+03:00", clock_out="2026-11-01T18:00:00+03:00")
    assert attendance.status == "present"
    absent = AttendanceIn(employee_id=1, shift_id=1, attendance_date="2026-11-02", status="absent")
    assert absent.clock_in is None
    with pytest.raises(ValidationError):
        AttendanceIn(employee_id=1, shift_id=1, attendance_date="2026-11-01")


def test_payroll_calculation_includes_approved_overtime_shift_premium_and_unpaid_leave():
    employee = HREmployee(
        id=7, organization_id=1, employee_number="EMP-007",
        first_name="Ada", last_name="Learner", hire_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        base_salary=Decimal("20000.00"), recurring_allowances={"transport": "1000.00"},
        recurring_benefits={"housing": "500.00"}, pension_contribution=Decimal("1000.00"),
    )
    rules = {
        "paye_bands": [
            {"lower_bound": "0", "upper_bound": "10000", "rate": "0.1"},
            {"lower_bound": "10000", "upper_bound": None, "rate": "0.2"},
        ],
        "personal_relief": "1000", "pension_tax_deductible_limit": "3000",
        "nssf_tiers": [
            {"lower_bound": "0", "upper_bound": "1000", "employee_rate": "0.06", "employer_rate": "0.06"},
            {"lower_bound": "1000", "upper_bound": "2000", "employee_rate": "0.06", "employer_rate": "0.06"},
        ],
        "shif_rate": "0.0275", "housing_levy_employee_rate": "0.015",
        "housing_levy_employer_rate": "0.015", "standard_monthly_hours": "173.33",
        "overtime_multiplier": "1.5",
    }
    result = _calculate(employee, rules, date(2026, 1, 1), date(2026, 1, 31),
                        overtime_minutes=120, weighted_differential_minutes="12",
                        unpaid_leave_days="2")
    assert Decimal(result["overtime_pay"]) > 0
    assert Decimal(result["shift_differential_pay"]) > 0
    assert result["unpaid_leave_deduction"] == "1290.32"
    assert Decimal(result["earned_gross"]) < Decimal(result["gross_pay"])
    assert Decimal(result["net_pay"]) > 0
