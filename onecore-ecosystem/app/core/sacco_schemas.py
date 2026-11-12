"""Validated contracts for SACCO membership, KYC and savings/share workflows."""
import re
from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class SaccoMemberCreateIn(BaseModel):
    member_number: str = Field(min_length=2, max_length=40, pattern=r"^[A-Z0-9][A-Z0-9/_-]{1,39}$")
    full_name: str = Field(min_length=3, max_length=180)
    phone: str = Field(min_length=8, max_length=20)
    email: EmailStr | None = None
    branch_id: str | None = Field(default=None, min_length=1, max_length=36)
    national_id: str = Field(min_length=6, max_length=20, pattern=r"^[A-Z0-9/-]{6,20}$")
    date_of_birth: date
    postal_address: str = Field(default="", max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @field_validator("member_number", mode="before")
    @classmethod
    def normalize_member_number(cls, value):
        return str(value or "").strip().upper()

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value):
        value = " ".join(str(value or "").split())
        if len(value) < 3:
            raise ValueError("Full name must contain at least three characters")
        return value

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone(cls, value):
        normalized = re.sub(r"[\s().-]", "", str(value or ""))
        if not re.fullmatch(r"\+?[0-9]{8,15}", normalized):
            raise ValueError("Phone must be an international or national number with 8 to 15 digits")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return str(value).strip().lower() if value else None

    @field_validator("national_id", mode="before")
    @classmethod
    def normalize_national_id(cls, value):
        return re.sub(r"\s+", "", str(value or "")).upper()

    @field_validator("idempotency_key")
    @classmethod
    def normalize_idempotency_key(cls, value):
        return value.strip()

    @model_validator(mode="after")
    def date_of_birth_not_in_future(self):
        if self.date_of_birth >= date.today():
            raise ValueError("Date of birth must be in the past")
        return self


class SaccoKycReviewIn(BaseModel):
    decision: str = Field(pattern=r"^(verify|reject)$")
    note: str = Field(min_length=5, max_length=500)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value):
        value = " ".join(str(value or "").split())
        if len(value) < 5:
            raise ValueError("A review note of at least five characters is required")
        return value


class SaccoFinancialTransactionIn(BaseModel):
    account_type: Literal["savings", "shares"]
    transaction_type: Literal["deposit", "withdrawal", "share_contribution"]
    amount: Decimal = Field(gt=Decimal("0"), max_digits=18, decimal_places=2)
    reference: str = Field(default="", max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @field_validator("reference")
    @classmethod
    def normalize_reference(cls, value):
        return " ".join(str(value or "").split())

    @field_validator("idempotency_key")
    @classmethod
    def normalize_financial_idempotency_key(cls, value):
        return value.strip()

    @model_validator(mode="after")
    def transaction_matches_account(self):
        if self.account_type == "savings" and self.transaction_type not in {"deposit", "withdrawal"}:
            raise ValueError("Savings accounts support deposits and withdrawals only")
        if self.account_type == "shares" and self.transaction_type != "share_contribution":
            raise ValueError("Share accounts support share contributions only in this release")
        return self


class SaccoWithdrawalDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=5, max_length=500)

    @field_validator("note")
    @classmethod
    def normalize_decision_note(cls, value):
        value = " ".join(str(value or "").split())
        if len(value) < 5:
            raise ValueError("A decision note of at least five characters is required")
        return value



class SaccoLoanProductCreateIn(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9_-]{1,31}$")
    name: str = Field(min_length=3, max_length=120)
    min_amount: Decimal = Field(gt=Decimal("0"), max_digits=18, decimal_places=2)
    max_amount: Decimal = Field(gt=Decimal("0"), max_digits=18, decimal_places=2)
    annual_interest_rate: Decimal = Field(ge=Decimal("0"), le=Decimal("100"), max_digits=7, decimal_places=4)
    min_term_months: int = Field(ge=1, le=120)
    max_term_months: int = Field(ge=1, le=120)
    max_debt_service_ratio: Decimal = Field(default=Decimal("0.4000"), gt=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        return str(value or "").strip().upper()

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value):
        value = " ".join(str(value or "").split())
        if len(value) < 3:
            raise ValueError("Product name must contain at least three characters")
        return value

    @model_validator(mode="after")
    def validate_product_ranges(self):
        if self.max_amount < self.min_amount:
            raise ValueError("Maximum loan amount must be at least the minimum amount")
        if self.max_term_months < self.min_term_months:
            raise ValueError("Maximum term must be at least the minimum term")
        return self


class SaccoLoanApplicationCreateIn(BaseModel):
    product_id: int = Field(gt=0)
    requested_amount: Decimal = Field(gt=Decimal("0"), max_digits=18, decimal_places=2)
    term_months: int = Field(ge=1, le=120)
    purpose: str = Field(min_length=10, max_length=500)
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
    def normalize_loan_idempotency_key(cls, value):
        return value.strip()


class SaccoLoanAssessmentIn(BaseModel):
    monthly_net_income: Decimal = Field(gt=Decimal("0"), max_digits=18, decimal_places=2)
    existing_monthly_debt: Decimal = Field(ge=Decimal("0"), max_digits=18, decimal_places=2)
    note: str = Field(min_length=5, max_length=500)

    @field_validator("note")
    @classmethod
    def normalize_assessment_note(cls, value):
        value = " ".join(str(value or "").split())
        if len(value) < 5:
            raise ValueError("Assessment note must contain at least five characters")
        return value


class SaccoLoanDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=5, max_length=500)

    @field_validator("note")
    @classmethod
    def normalize_loan_decision_note(cls, value):
        value = " ".join(str(value or "").split())
        if len(value) < 5:
            raise ValueError("Decision note must contain at least five characters")
        return value


class SaccoLoanDisbursementIn(BaseModel):
    reference: str = Field(default="", max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @field_validator("reference")
    @classmethod
    def normalize_disbursement_reference(cls, value):
        return " ".join(str(value or "").split())

    @field_validator("idempotency_key")
    @classmethod
    def normalize_disbursement_key(cls, value):
        return value.strip()


class SaccoLoanRepaymentIn(BaseModel):
    amount: Decimal = Field(gt=Decimal("0"), max_digits=18, decimal_places=2)
    reference: str = Field(default="", max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @field_validator("reference")
    @classmethod
    def normalize_repayment_reference(cls, value):
        return " ".join(str(value or "").split())

    @field_validator("idempotency_key")
    @classmethod
    def normalize_repayment_key(cls, value):
        return value.strip()
