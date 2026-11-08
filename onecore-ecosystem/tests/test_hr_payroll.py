from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from types import SimpleNamespace
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.hr_payroll import (
    LeaveIn, PayrollRunIn, RuleSetIn, PayrollPaymentBatchIn, PayrollBatchSettlementIn, PayrollStatementImportIn, _calculate, _progressive_tax, _tiered_contribution, require_payroll_action,
)
from app.core.hr_payroll_models import HREmployee, HRLeaveRequest, PayrollRuleSet, PayrollRun, PayrollPayslip, PayrollAccountingMapping, PayrollAccountingLink, HRAttendanceRecord, PayrollPaymentBatch, PayrollPaymentBatchItem, PayrollBankStatementLine
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
    assert "uq_payroll_run_org_idempotency" in {x.name for x in PayrollRun.__table__.indexes}
    assert "uq_payroll_payslip_run_employee" in {x.name for x in PayrollPayslip.__table__.indexes}


def test_hr_payroll_routes_are_registered():
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/hr/employees", "/api/v1/hr/employees/{employee_id}/employment-status",
        "/api/v1/hr/employees/{employee_id}/leave",
        "/api/v1/hr/leave-requests", "/api/v1/hr/leave-requests/{request_id}/decision",
        "/api/v1/hr/attendance", "/api/v1/hr/attendance/{attendance_id}/decision",
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



def test_attendance_domain_model_and_overtime_duration_validation():
    assert HRAttendanceRecord.__tablename__ == "hr_attendance_records"
    assert "uq_hr_attendance_org_employee_date" in {x.name for x in HRAttendanceRecord.__table__.indexes}
    from app.api.hr_payroll import AttendanceIn
    payload = AttendanceIn(
        employee_id=1, work_date="2026-11-08",
        clock_in="2026-11-08T08:00:00+03:00",
        clock_out="2026-11-08T18:00:00+03:00",
        break_minutes=60, scheduled_minutes=480,
        idempotency_key="attendance-emp1-20261108",
    )
    worked = int((payload.clock_out - payload.clock_in).total_seconds() // 60) - payload.break_minutes
    assert worked == 540
    assert worked - payload.scheduled_minutes == 60
    with pytest.raises(ValidationError):
        AttendanceIn(
            employee_id=1, work_date="2026-11-08",
            clock_in="2026-11-08T08:00:00",
            clock_out="2026-11-08T18:00:00",
            idempotency_key="attendance-invalid",
        )
    with pytest.raises(ValidationError):
        AttendanceIn(
            employee_id=1, work_date="2026-11-08",
            clock_in="2026-11-08T18:00:00+03:00",
            clock_out="2026-11-08T08:00:00+03:00",
            idempotency_key="attendance-invalid2",
        )


def test_payroll_applies_approved_overtime_and_unpaid_leave_adjustments():
    employee = HREmployee(
        id=9, organization_id=1, employee_number="EMP-009",
        first_name="Grace", last_name="Worker",
        hire_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        base_salary=Decimal("20000.00"),
        recurring_allowances={"transport": "1000.00"},
        recurring_benefits={"housing": "500.00"},
        pension_contribution=Decimal("1000.00"),
    )
    employee.overtime_multiplier = Decimal("1.50")
    employee.scheduled_minutes_per_day = 480
    rules = {
        "paye_bands": [{"lower_bound": "0", "upper_bound": None, "rate": "0.1"}],
        "personal_relief": "1000",
        "pension_tax_deductible_limit": "3000",
        "nssf_tiers": [{"lower_bound": "0", "upper_bound": "100000", "employee_rate": "0.06", "employer_rate": "0.06"}],
        "shif_rate": "0.0275",
        "housing_levy_employee_rate": "0.015",
        "housing_levy_employer_rate": "0.015",
    }
    result = _calculate(employee, rules, date(2026, 1, 1), date(2026, 1, 31),
                        overtime_minutes=60, unpaid_leave_days=Decimal("2"))
    assert result["overtime_minutes"] == 60
    assert result["overtime_earnings"] == "144.23"
    assert result["unpaid_leave_days"] == "2"
    assert result["unpaid_leave_deduction"] == "1290.32"
    assert result["gross_pay"] == "20353.91"


def test_overtime_requires_explicit_employee_policy():
    employee = HREmployee(
        id=10, organization_id=1, employee_number="EMP-010",
        first_name="Sam", last_name="Worker",
        hire_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        base_salary=Decimal("20000.00"),
    )
    employee.overtime_multiplier = None
    employee.scheduled_minutes_per_day = 480
    rules = {
        "paye_bands": [{"lower_bound": "0", "upper_bound": None, "rate": "0.1"}],
        "personal_relief": "0", "pension_tax_deductible_limit": "0",
        "nssf_tiers": [{"lower_bound": "0", "upper_bound": "100000", "employee_rate": "0", "employer_rate": "0"}],
        "shif_rate": "0", "housing_levy_employee_rate": "0", "housing_levy_employer_rate": "0",
    }
    with pytest.raises(HTTPException) as error:
        _calculate(employee, rules, date(2026, 1, 1), date(2026, 1, 31), overtime_minutes=30)
    assert error.value.status_code == 409



def test_payroll_payment_batch_and_statement_models_are_tenant_scoped():
    assert PayrollPaymentBatch.__tablename__ == "payroll_payment_batches"
    assert PayrollPaymentBatchItem.__tablename__ == "payroll_payment_batch_items"
    assert PayrollBankStatementLine.__tablename__ == "payroll_bank_statement_lines"
    assert "uq_payroll_payment_batch_org_idempotency" in {
        x.name for x in PayrollPaymentBatch.__table__.indexes
    }
    assert "uq_payroll_batch_item_org_reference" in {
        x.name for x in PayrollPaymentBatchItem.__table__.indexes
    }
    assert "uq_payroll_bank_statement_fingerprint" in {
        x.name for x in PayrollBankStatementLine.__table__.indexes
    }


def test_payroll_payment_batch_routes_are_registered():
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/payroll/payment-batches",
        "/api/v1/payroll/payment-batches/{batch_id}/submit",
        "/api/v1/payroll/payment-batches/{batch_id}/approve",
        "/api/v1/payroll/payment-batches/{batch_id}/settlements",
        "/api/v1/payroll/bank-statements/import",
        "/api/v1/payroll/bank-statements",
        "/api/v1/payroll/bank-statements/{line_id}/resolve",
    }
    assert expected.issubset(paths)


def test_payment_batch_payloads_reject_duplicates_and_invalid_amounts():
    payload = PayrollPaymentBatchIn(
        payroll_run_ids=[11, 12], idempotency_key="batch-november-2026"
    )
    assert payload.payroll_run_ids == [11, 12]
    with pytest.raises(ValidationError):
        PayrollPaymentBatchIn(
            payroll_run_ids=[11, 11], idempotency_key="batch-november-2026"
        )
    with pytest.raises(ValidationError):
        PayrollBatchSettlementIn(items=[
            {"payroll_run_id": 11, "payment_reference": "BANK-001"},
            {"payroll_run_id": 11, "payment_reference": "BANK-002"},
        ])
    with pytest.raises(ValidationError):
        PayrollStatementImportIn(lines=[
            {"transaction_date": "2026-11-08", "reference": "BANK-001", "amount": "-1"}
        ])
