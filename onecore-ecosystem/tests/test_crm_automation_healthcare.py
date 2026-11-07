from datetime import datetime, timezone
from cryptography.fernet import Fernet
from fastapi import HTTPException
import pytest
from app.core.config import settings
from app.core.models import (CRMCommunicationTemplate, CRMAudienceSegment, CRMCampaignSchedule,
    CRMCampaignRecipient, HealthcarePatient, HealthcareEncounter, HealthcarePatientAccess,
    HealthcareConsent, HealthcareAccessAudit, HealthcareRoleAssignment,
    HealthcareBreakGlassSession, HealthcareAppointment)
from app.main import app
from app.api.crm_automation import compile_rules, _validate_template
from app.api.healthcare_privacy import encrypt, decrypt, ROLE_PERMISSIONS
from app.services.crm_scheduler import render_template, next_occurrence


def test_crm_automation_and_healthcare_routes_registered():
    paths=set(app.openapi()["paths"])
    expected=[
        "/api/v1/crm/templates","/api/v1/crm/templates/{template_id}","/api/v1/crm/templates/{template_id}/versions",
        "/api/v1/crm/segments","/api/v1/crm/segments/{segment_id}",
        "/api/v1/crm/segments/{segment_id}/deactivate",
        "/api/v1/crm/segments/{segment_id}/preview",
        "/api/v1/crm/campaigns/{campaign_id}/schedule","/api/v1/crm/schedules",
        "/api/v1/crm/campaigns/{campaign_id}/schedule/pause",
        "/api/v1/crm/campaigns/{campaign_id}/schedule/resume",
        "/api/v1/crm/campaigns/{campaign_id}/schedule",
        "/api/v1/crm/scheduler/run-due",
        "/api/v1/crm/campaigns/{campaign_id}/apply-template/{template_id}",
        "/api/v1/healthcare/access/roles","/api/v1/healthcare/access/roles/{role_id}/revoke",
        "/api/v1/healthcare/patients","/api/v1/healthcare/patients/{patient_id}",
        "/api/v1/healthcare/patients/{patient_id}/access",
        "/api/v1/healthcare/patients/{patient_id}/access/{grant_id}/revoke",
        "/api/v1/healthcare/patients/{patient_id}/encounters",
        "/api/v1/healthcare/patients/{patient_id}/consents",
        "/api/v1/healthcare/patients/{patient_id}/break-glass",
        "/api/v1/healthcare/break-glass/{session_id}/close",
        "/api/v1/healthcare/patients/{patient_id}/appointments",
        "/api/v1/healthcare/encounters/{encounter_id}/close",
        "/api/v1/healthcare/audit",
    ]
    for path in expected:assert path in paths,path
    assert CRMCommunicationTemplate.__tablename__=="crm_communication_templates"
    assert CRMAudienceSegment.__tablename__=="crm_audience_segments"
    assert CRMCampaignSchedule.__tablename__=="crm_campaign_schedules"
    assert hasattr(CRMCampaignSchedule,"recurrence") and hasattr(CRMCampaignSchedule,"last_run_at")
    assert hasattr(CRMCampaignRecipient,"message_snapshot")
    assert HealthcarePatient.__tablename__=="healthcare_patients"
    assert HealthcareEncounter.__tablename__=="healthcare_encounters"
    assert HealthcarePatientAccess.__tablename__=="healthcare_patient_access"
    assert HealthcareConsent.__tablename__=="healthcare_consents"
    assert HealthcareAccessAudit.__tablename__=="healthcare_access_audits"
    assert HealthcareRoleAssignment.__tablename__=="healthcare_role_assignments"
    assert HealthcareBreakGlassSession.__tablename__=="healthcare_break_glass_sessions"
    assert HealthcareAppointment.__tablename__=="healthcare_appointments"


def test_nested_segment_rules_are_validated_and_compiled():
    rules={"all":[{"field":"company","op":"contains","value":"clinic"}],
        "any":[{"field":"email","op":"not_empty"},{"all":[
            {"field":"phone","op":"starts_with","value":"+254"},
            {"field":"full_name","op":"ne","value":""}
        ]}]}
    expression=compile_rules(rules)
    assert expression is not None
    assert "crm_contacts" in str(expression)
    with pytest.raises(HTTPException):
        compile_rules({"all":[{"field":"password_hash","op":"eq","value":"x"}]})
    with pytest.raises(HTTPException):
        compile_rules({"any":[{"field":"email","op":"raw_sql","value":"x"}]})
    nested={"all":[{"field":"company","op":"eq","value":"x"}]}
    for _ in range(5):nested={"any":[nested]}
    with pytest.raises(HTTPException):compile_rules(nested)
    with pytest.raises(HTTPException):compile_rules({"all":[]})


def test_template_variables_are_allowlisted_and_personalized():
    assert _validate_template("Hi {{first_name}}","Hello {{full_name}}",[])==["first_name","full_name"]
    with pytest.raises(HTTPException):
        _validate_template("{{password}}","secret",[])
    class Template:
        variables=["first_name","company","campaign_name"]
    class Contact:
        full_name="Ada Lovelace"
        email="ada@example.test"
        phone="+254700000000"
        company="Analytical Engines"
    assert render_template("Hello {{first_name}} at {{company}}",Template(),Contact(),"Launch")=="Hello Ada at Analytical Engines"
    with pytest.raises(ValueError):
        render_template("{{medical_record}}",Template(),Contact(),"Launch")


def test_daily_schedule_preserves_local_time_across_dst():
    scheduled=datetime(2026,3,7,14,0,tzinfo=timezone.utc)
    now=datetime(2026,3,7,15,0,tzinfo=timezone.utc)
    assert next_occurrence(scheduled,"daily",now,"America/New_York")==datetime(2026,3,8,13,0,tzinfo=timezone.utc)


def test_healthcare_phi_is_encrypted_and_key_required(monkeypatch):
    monkeypatch.setattr(settings,"healthcare_phi_encryption_key",Fernet.generate_key().decode())
    original={"diagnosis":"private","patient_name":"Example"}
    encrypted=encrypt(original)
    assert "private" not in encrypted
    assert decrypt(encrypted)==original
    monkeypatch.setattr(settings,"healthcare_phi_encryption_key","")
    with pytest.raises(HTTPException) as exc:encrypt(original)
    assert exc.value.status_code==503


def test_healthcare_role_matrix_is_least_privilege():
    assert "clinical.write" in ROLE_PERMISSIONS["clinician"]
    assert "clinical.write" not in ROLE_PERMISSIONS["nurse"]
    assert "clinical.read" not in ROLE_PERMISSIONS["receptionist"]
    assert "patient.read" not in ROLE_PERMISSIONS["receptionist"]
    assert "audit.read" in ROLE_PERMISSIONS["privacy_officer"]
    assert "patient.read" not in ROLE_PERMISSIONS["privacy_officer"]
    assert "breakglass" in ROLE_PERMISSIONS["clinician"]
