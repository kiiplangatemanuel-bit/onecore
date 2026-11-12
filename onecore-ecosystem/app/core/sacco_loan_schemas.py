"""Validated request contracts for SACCO loan origination and credit governance."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SaccoLoanProductCreateIn(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9_-]{1,31}$")
    name: str = Field(min_length=3, max_length=120)
    branch_id: str | None = Field(default=None, min_length=1, max_length=36)
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    minimum_principal: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    maximum_principal: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    annual_interest_rate_bps: int = Field(ge=0, le=6000)
    minimum_term_months: int = Field(ge=1, le=120)
    maximum_term_months: int = Field(ge=1, le=120)
    minimum_guarantors: int = Field(default=0, ge=0, le=5)
    maximum_debt_service_ratio_bps: int = Field(default=4000, ge=1000, le=8000)
    requires_collateral: bool = False

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        return str(value or "").strip().upper()

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value):
        value = " ".join(str(value or "").split())
        if len(value) < 3:
            raise ValueError("Loan product name must contain at least three characters")
        return value

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value):
        return str(value or "").strip().upper()

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.maximum_principal < self.minimum_principal:
            raise ValueError("Maximum principal must not be lower than minimum principal")
        if self.maximum_term_months < self.minimum_term_months:
            raise ValueError("Maximum term must not be lower than minimum term")
        return self


class SaccoLoanApplicationCreateIn(BaseModel):
    member_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    principal: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    term_months: int = Field(ge=1, le=120)
    purpose: str = Field(min_length=10, max_length=500)
    monthly_net_income: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    monthly_existing_debt: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=18, decimal_places=2)
    first_repayment_date: date
    idempotency_key: str = Field(min_length=8, max_length=100)

    @field_validator("purpose")
    @classmethod
    def normalize_purpose(cls, value):
        value = " ".join(str(value or "").split())
        if len(value) < 10:
            raise ValueError("Loan purpose must contain at least ten characters")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def normalize_key(cls, value):
        return value.strip()

    @model_validator(mode="after")
    def validate_first_due_date(self):
        if self.first_repayment_date <= date.today():
            raise ValueError("First repayment date must be in the future")
        return self


class SaccoLoanGuarantorCreateIn(BaseModel):
    member_id: int = Field(gt=0)
    guaranteed_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class SaccoLoanGuarantorConsentIn(BaseModel):
    decision: Literal["accept", "reject"]
    consent_reference: str = Field(min_length=3, max_length=120)
    note: str = Field(min_length=5, max_length=500)

    @field_validator("consent_reference", "note")
    @classmethod
    def normalize_consent_text(cls, value):
        value = " ".join(str(value or "").split())
        if len(value) < 3:
            raise ValueError("Consent evidence reference and note are required")
        return value


class SaccoLoanCollateralCreateIn(BaseModel):
    collateral_type: str = Field(min_length=3, max_length=40)
    description: str = Field(min_length=5, max_length=500)
    declared_value: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    document_reference: str = Field(min_length=3, max_length=120)

    @field_validator("collateral_type", "description", "document_reference")
    @classmethod
    def normalize_collateral_text(cls, value):
        return " ".join(str(value or "").split())


class SaccoLoanCollateralVerificationIn(BaseModel):
    decision: Literal["verify", "reject"]
    note: str = Field(min_length=5, max_length=500)

    @field_validator("note")
    @classmethod
    def normalize_verification_note(cls, value):
        return " ".join(str(value or "").split())


class SaccoLoanAssessmentIn(BaseModel):
    note: str = Field(min_length=5, max_length=500)

    @field_validator("note")
    @classmethod
    def normalize_assessment_note(cls, value):
        return " ".join(str(value or "").split())


class SaccoLoanDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=5, max_length=500)

    @field_validator("note")
    @classmethod
    def normalize_decision_note(cls, value):
        return " ".join(str(value or "").split())
