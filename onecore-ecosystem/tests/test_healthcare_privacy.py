from datetime import date, datetime, timezone, timedelta
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from app.core.config import settings
from app.core.models import (HealthcarePatient, HealthcarePatientAccessGrant,
    HealthcarePatientConsent, HealthcareBreakGlassSession, HealthcareAccessAudit,
    HealthcareRoleAssignment, HealthcareEncounter)
from app.core.automation_healthcare_schemas import HealthcarePatientIn, HealthcareBreakGlassIn
from app.services.healthcare_crypto import encrypt_health_data, decrypt_health_data
from app.api.healthcare_privacy import ROLE_PERMISSIONS
from app.main import app


def test_healthcare_privacy_models_and_routes_are_registered():
    assert HealthcarePatient.__tablename__=="healthcare_patients"
    assert "identity_ciphertext" in HealthcarePatient.__table__.c
    assert "first_name" not in HealthcarePatient.__table__.c
    assert HealthcareEncounter.__tablename__=="healthcare_encounters"
    assert "clinical_ciphertext" in HealthcareEncounter.__table__.c
    assert HealthcarePatientAccessGrant.__tablename__=="healthcare_patient_access_grants"
    assert HealthcarePatientConsent.__tablename__=="healthcare_patient_consents"
    assert HealthcareBreakGlassSession.__tablename__=="healthcare_break_glass_sessions"
    assert HealthcareAccessAudit.__tablename__=="healthcare_access_audit"
    assert HealthcareRoleAssignment.__tablename__=="healthcare_role_assignments"
    paths=app.openapi()["paths"]
    assert "/api/v1/healthcare/access/roles" in paths
    assert "/api/v1/healthcare/access/roles/{role_id}/revoke" in paths
    assert "/api/v1/healthcare/patients" in paths
    assert "/api/v1/healthcare/patients/{patient_id}/access-grants" in paths
    assert "/api/v1/healthcare/patients/{patient_id}/consents" in paths
    assert "/api/v1/healthcare/patients/{patient_id}/break-glass" in paths
    assert "/api/v1/healthcare/patients/{patient_id}/encounters" in paths
    assert "/api/v1/healthcare/encounters/{encounter_id}/sign" in paths
    assert "/api/v1/healthcare/audit" in paths
    assert "/healthcare" in paths


def test_healthcare_identity_and_clinical_data_are_authenticated_encryption(monkeypatch):
    monkeypatch.setattr(settings,"healthcare_encryption_key","")
    monkeypatch.setattr(settings,"secret_key","test-only-secret-key-for-healthcare")
    payload={"first_name":"Ada","phone":"+254700000000"}
    ciphertext=encrypt_health_data(payload)
    assert "Ada" not in ciphertext
    assert decrypt_health_data(ciphertext)==payload


def test_healthcare_encryption_refuses_unsafe_default_key(monkeypatch):
    monkeypatch.setattr(settings,"healthcare_encryption_key","")
    monkeypatch.setattr(settings,"secret_key","unsafe-development-key-change-me")
    with pytest.raises(RuntimeError):
        encrypt_health_data({"clinical_notes":"private"})


def test_healthcare_role_matrix_is_least_privilege():
    assert "clinical.write" in ROLE_PERMISSIONS["clinician"]
    assert "clinical.write" not in ROLE_PERMISSIONS["nurse"]
    assert "clinical.read" not in ROLE_PERMISSIONS["receptionist"]
    assert "audit.read" in ROLE_PERMISSIONS["privacy_officer"]
    assert "patient.read" not in ROLE_PERMISSIONS["privacy_officer"]
    assert "breakglass" in ROLE_PERMISSIONS["clinician"]


def test_patient_schema_rejects_blank_names_and_future_birth_date():
    with pytest.raises(ValidationError):
        HealthcarePatientIn(patient_number="PT-1",first_name=" ",last_name="Patient")
    with pytest.raises(ValidationError):
        HealthcarePatientIn(patient_number="PT-2",first_name="Ada",last_name="Patient",
            date_of_birth=date.today()+timedelta(days=1))
    valid=HealthcarePatientIn(patient_number="PT-3",first_name=" Ada ",last_name="Patient")
    assert valid.first_name=="Ada"


def test_break_glass_requires_specific_justification():
    assert HealthcareBreakGlassIn(justification="Immediate emergency clinical treatment").justification
    with pytest.raises(ValidationError):
        HealthcareBreakGlassIn(justification="urgent")
