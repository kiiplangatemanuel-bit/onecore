from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, EmailStr, field_validator, model_validator


class CRMTemplateIn(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    channel: Literal["email", "sms", "whatsapp"]
    purpose: Literal["marketing", "transactional"] = "marketing"
    subject: str = Field(default="", max_length=180)
    body: str = Field(min_length=1, max_length=5000)
    branch_id: str | None = Field(default=None, max_length=36)


class CRMSegmentIn(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    branch_id: str | None = Field(default=None, max_length=36)
    filters: dict[str, Any] = Field(default_factory=lambda: {"logic": "and", "conditions": []})


class CRMCampaignScheduleIn(BaseModel):
    scheduled_at: datetime
    timezone: str = Field(default="Africa/Nairobi", min_length=1, max_length=80)
    recurrence: Literal["once", "daily", "weekly"] = "once"
    template_id: int | None = Field(default=None, gt=0)
    segment_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def aware_datetime(self):
        if self.scheduled_at.tzinfo is None or self.scheduled_at.utcoffset() is None:
            raise ValueError("scheduled_at must include a timezone offset")
        return self


class HealthcareRoleAssignmentIn(BaseModel):
    user_id: int = Field(gt=0)
    branch_id: str | None = Field(default=None, max_length=36)
    role: Literal["healthcare_admin", "clinician", "nurse", "receptionist", "privacy_officer", "lab_technician", "pharmacist"]


class HealthcarePatientIn(BaseModel):
    patient_number: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9._/-]+$")
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    date_of_birth: str | None = None
    phone: str | None = Field(default=None, min_length=7, max_length=32)
    email: EmailStr | None = None
    emergency_contact_name: str = Field(default="", max_length=180)
    emergency_contact_phone: str = Field(default="", max_length=32)
    branch_id: str | None = Field(default=None, max_length=36)

    @field_validator("first_name", "last_name")
    @classmethod
    def names_not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Patient name is required")
        return value


class HealthcarePatientGrantIn(BaseModel):
    user_id: int = Field(gt=0)
    permissions: list[Literal["patient.read", "clinical.read", "clinical.write", "appointment.manage"]] = Field(min_length=1)
    reason: str = Field(min_length=5, max_length=500)
    expires_at: datetime | None = None


class HealthcareConsentIn(BaseModel):
    purpose: Literal["treatment", "data_processing", "data_sharing", "research", "marketing"]
    decision: Literal["granted", "revoked"]
    evidence_reference: str = Field(default="", max_length=180)
    notes: str = Field(default="", max_length=500)
    expires_at: datetime | None = None


class HealthcareBreakGlassIn(BaseModel):
    justification: str = Field(min_length=15, max_length=1000)


class HealthcareEncounterIn(BaseModel):
    chief_complaint: str = Field(min_length=2, max_length=500)
    clinical_notes: str = Field(default="", max_length=12000)
    assessment: str = Field(default="", max_length=6000)
    plan: str = Field(default="", max_length=6000)


class HealthcareAppointmentIn(BaseModel):
    patient_id: int = Field(gt=0)
    provider_user_id: int = Field(gt=0)
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def validate_window(self):
        if not self.starts_at.tzinfo or not self.ends_at.tzinfo:
            raise ValueError("Appointment times must be timezone-aware")
        if self.ends_at <= self.starts_at:
            raise ValueError("Appointment end must follow start")
        return self
