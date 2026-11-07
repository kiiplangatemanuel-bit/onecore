from datetime import date, datetime, timezone, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.models import HealthcarePatient, HealthcareAppointment, HealthcareEncounter
from app.core.schemas import (
    HealthcarePatientIn, HealthcareAppointmentIn, HealthcareAppointmentStatusIn,
    HealthcareEncounterIn,
)
from app.services.healthcare import validate_appointment_transition
from app.main import app


def test_healthcare_patient_contract_normalizes_names_and_validates_contacts():
    patient = HealthcarePatientIn(
        patient_number="pt-0001", first_name=" Ada ", last_name=" Patient ",
        date_of_birth=date(1990, 1, 2), phone="+254700000000",
    )
    assert patient.first_name.strip() == "Ada"
    assert patient.patient_number == "pt-0001"
    with pytest.raises(ValidationError):
        HealthcarePatientIn(patient_number="x", first_name="Ada", last_name="Patient")
    with pytest.raises(ValidationError):
        HealthcarePatientIn(patient_number="PT-2", first_name=" ", last_name="Patient")
    with pytest.raises(ValidationError):
        HealthcarePatientIn(patient_number="PT-3", first_name="Future", last_name="Patient",
                            date_of_birth=date.today() + timedelta(days=1))


def test_appointment_requires_timezone_and_positive_duration():
    start = datetime(2026, 11, 8, 9, 0, tzinfo=timezone(timedelta(hours=3)))
    end = start + timedelta(minutes=30)
    row = HealthcareAppointmentIn(
        patient_id=1, provider_user_id=2, starts_at=start, ends_at=end,
        reason="Consultation",
    )
    assert row.ends_at > row.starts_at
    with pytest.raises(ValidationError):
        HealthcareAppointmentIn(
            patient_id=1, provider_user_id=2,
            starts_at=datetime(2026, 11, 8, 9, 0),
            ends_at=datetime(2026, 11, 8, 10, 0),
        )
    with pytest.raises(ValidationError):
        HealthcareAppointmentIn(
            patient_id=1, provider_user_id=2, starts_at=end, ends_at=start,
        )


def test_appointment_status_contract_and_lifecycle():
    assert HealthcareAppointmentStatusIn(status="checked_in").status == "checked_in"
    validate_appointment_transition("scheduled", "checked_in")
    validate_appointment_transition("checked_in", "completed")
    with pytest.raises(HTTPException) as exc:
        validate_appointment_transition("completed", "scheduled")
    assert exc.value.status_code == 409
    with pytest.raises(ValidationError):
        HealthcareAppointmentStatusIn(status="rescheduled")


def test_encounter_requires_a_chief_complaint():
    encounter = HealthcareEncounterIn(chief_complaint="Headache", assessment="Review")
    assert encounter.chief_complaint == "Headache"
    with pytest.raises(ValidationError):
        HealthcareEncounterIn(chief_complaint="  ")


def test_healthcare_models_and_api_routes_are_registered():
    assert HealthcarePatient.__tablename__ == "healthcare_patients"
    assert HealthcareAppointment.__tablename__ == "healthcare_appointments"
    assert HealthcareAppointment.__table__.c.status_note.default.arg == ""
    assert HealthcareEncounter.__tablename__ == "healthcare_encounters"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/healthcare/patients" in paths
    assert "/api/v1/healthcare/patients/{patient_id}" in paths
    assert "/api/v1/healthcare/appointments" in paths
    assert "/api/v1/healthcare/appointments/{appointment_id}/status" in paths
    assert "/api/v1/healthcare/appointments/{appointment_id}/encounter" in paths
    assert "/api/v1/healthcare/encounters/{encounter_id}/sign" in paths
    assert "/healthcare" in paths


def test_healthcare_workspace_exposes_registration_scheduling_and_encounter_controls():
    from pathlib import Path
    page = Path(__file__).resolve().parents[1] / "app" / "web" / "healthcare.html"
    html = page.read_text(encoding="utf-8")
    assert 'id="patient"' in html
    assert 'id="appointment"' in html
    assert 'id="encounter"' in html
    assert "Sign encounter" in html
