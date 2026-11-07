from decimal import Decimal

from fastapi import HTTPException
import pytest

from app.api.payroll_completion import (
    KENYA_2026_RULES,
    _validate_authority_sources,
    _validate_rule_parameters,
    calculate_kenya_payroll,
    money,
)


def test_kenya_seed_rule_pack_is_draft_until_independent_activation():
    assert KENYA_2026_RULES["status"] == "draft"
    assert KENYA_2026_RULES["effective_from"] == "2026-02-01"
    assert KENYA_2026_RULES["parameters"]["nssf"] == {
        "rate": "0.06",
        "lower_earnings_limit": "9000",
        "upper_earnings_limit": "108000",
    }


def test_kenya_statutory_source_evidence_requires_kra_nssf_and_sha_or_kenya_law():
    sources = [
        {"authority": "KRA", "url": "https://www.kra.go.ke/individual/filing-paying/types-of-taxes/paye"},
        {"authority": "NSSF", "url": "https://www.nssf.or.ke/notice-to-employers-year-4-2026-nssf-contribution-rates"},
        {"authority": "Kenya Law / SHA", "url": "https://new.kenyalaw.org/akn/ke/act/ln/2024/49/eng%402024-03-08/source.pdf"},
    ]
    _validate_authority_sources(sources)
    with pytest.raises(HTTPException):
        _validate_authority_sources(sources[:2])


def test_rule_validation_rejects_non_contiguous_or_unlimited_middle_tax_band():
    invalid = {
        "paye": {
            "bands": [
                {"lower": "0", "upper": "24000", "rate": "0.10"},
                {"lower": "25000", "upper": None, "rate": "0.25"},
            ],
            "pension_monthly_limit": "30000",
            "mortgage_monthly_limit": "30000",
            "prmf_monthly_limit": "15000",
            "personal_relief_monthly": "2400",
            "insurance_relief_rate": "0.15",
            "insurance_relief_monthly_limit": "5000",
        },
        "nssf": {"rate": "0.06", "lower_earnings_limit": "9000", "upper_earnings_limit": "108000"},
        "shif": {"rate": "0.0275", "minimum": "300"},
        "housing_levy": {"employee_rate": "0.015", "employer_rate": "0.015"},
    }
    with pytest.raises(HTTPException):
        _validate_rule_parameters(invalid)


def test_kenya_statutory_calculation_preserves_decimal_rounding_and_employer_cost():
    result = calculate_kenya_payroll(Decimal("100000"), {"resident_for_tax": True}, KENYA_2026_RULES)
    assert Decimal(result["nssf_employee"]) == Decimal("6000.00")
    assert Decimal(result["nssf_employer"]) == Decimal("6000.00")
    assert Decimal(result["shif_employee"]) == Decimal("2750.00")
    assert Decimal(result["housing_levy_employee"]) == Decimal("1500.00")
    assert Decimal(result["housing_levy_employer"]) == Decimal("1500.00")
    assert Decimal(result["net_pay"]) == Decimal("70441.65")
    assert Decimal(result["total_employer_cost"]) == Decimal("107500.00")
    assert money("1.005") == Decimal("1.01")


def test_paye_relief_does_not_reduce_tax_below_zero():
    result = calculate_kenya_payroll(Decimal("10000"), {"resident_for_tax": True}, KENYA_2026_RULES)
    assert Decimal(result["paye"]) == Decimal("0.00")
    assert Decimal(result["net_pay"]) >= Decimal("0.00")
