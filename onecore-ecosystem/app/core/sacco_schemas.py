"""Validated contracts for the SACCO membership/KYC vertical slice."""
import re
from datetime import date
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
