from decimal import Decimal

from app.api.payroll_completion import calculate_kenya_payroll, KENYA_2026_RULES, money


def test_kenya_2026_statutory_calculation_and_employer_costs():
    result = calculate_kenya_payroll(Decimal("100000"), {"resident_for_tax": True},
                                    KENYA_2026_RULES)
    assert Decimal(result["nssf_employee"]) == Decimal("6000.00")
    assert Decimal(result["nssf_employer"]) == Decimal("6000.00")
    assert Decimal(result["shif_employee"]) == Decimal("2750.00")
    assert Decimal(result["housing_levy_employee"]) == Decimal("1500.00")
    assert Decimal(result["housing_levy_employer"]) == Decimal("1500.00")
    assert Decimal(result["net_pay"]) == Decimal("74924.90")
    assert Decimal(result["total_employer_cost"]) == Decimal("107500.00")


def test_nssf_upper_limit_and_shif_minimum():
    high = calculate_kenya_payroll(Decimal("250000"), {}, KENYA_2026_RULES)
    assert Decimal(high["nssf_employee"]) == Decimal("6480.00")
    low = calculate_kenya_payroll(Decimal("5000"), {}, KENYA_2026_RULES)
    assert Decimal(low["shif_employee"]) == Decimal("300.00")
    assert Decimal(low["housing_levy_employee"]) == Decimal("75.00")


def test_nonresident_does_not_receive_personal_relief():
    resident = calculate_kenya_payroll(Decimal("50000"), {"resident_for_tax": True}, KENYA_2026_RULES)
    nonresident = calculate_kenya_payroll(Decimal("50000"), {"resident_for_tax": False}, KENYA_2026_RULES)
    assert Decimal(resident["personal_relief"]) == Decimal("2400.00")
    assert Decimal(nonresident["personal_relief"]) == Decimal("0.00")
    assert Decimal(nonresident["paye"]) > Decimal(resident["paye"])


def test_qualifying_pension_and_other_allowable_deductions_are_capped():
    result = calculate_kenya_payroll(Decimal("150000"), {}, KENYA_2026_RULES, {
        "employee_pension": "50000", "mortgage_interest": "40000",
        "post_retirement_medical_fund": "20000", "insurance_premium": "50000"
    })
    assert Decimal(result["employee_pension"]) == Decimal("30000.00")
    assert Decimal(result["mortgage_interest"]) == Decimal("30000.00")
    assert Decimal(result["post_retirement_medical_fund"]) == Decimal("15000.00")
    assert Decimal(result["insurance_relief"]) == Decimal("5000.00")
