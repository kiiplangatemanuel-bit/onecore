from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.api.hr_payroll import (
    LeaveIn, RuleSetIn, _calculate, _progressive_tax, _tiered_contribution,
)
from app.core.hr_payroll_models import HREmployee, HRLeaveRequest, PayrollRuleSet, PayrollRun, PayrollPayslip
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
    assert "uq_payroll_run_org_idempotency" in {x.name for x in PayrollRun.__table__.indexes}
    assert "uq_payroll_payslip_run_employee" in {x.name for x in PayrollPayslip.__table__.indexes}


def test_hr_payroll_routes_are_registered():
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/hr/employees", "/api/v1/hr/employees/{employee_id}/leave",
        "/api/v1/hr/leave-requests", "/api/v1/hr/leave-requests/{request_id}/decision",
        "/api/v1/payroll/rule-sets", "/api/v1/payroll/rule-sets/{rule_set_id}/submit",
        "/api/v1/payroll/rule-sets/{rule_set_id}/approve", "/api/v1/payroll/runs",
        "/api/v1/payroll/runs/{run_id}/submit", "/api/v1/payroll/runs/{run_id}/approve",
        "/api/v1/payroll/runs/{run_id}/mark-paid", "/api/v1/payroll/runs/{run_id}/payslips",
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
        first_name="Ada", last_name="Learner", base_salary=Decimal("20000.00"),
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
    result = _calculate(employee, rules)
    assert result["gross_pay"] == "21500.00"
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
