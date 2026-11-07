from cryptography.fernet import Fernet
from fastapi import HTTPException
import pytest
from app.core.config import settings
from app.core.models import (CRMCommunicationTemplate, CRMAudienceSegment, CRMCampaignSchedule,
    HealthcarePatient, HealthcareEncounter, HealthcarePatientAccess, HealthcareConsent, HealthcareAccessAudit)
from app.main import app
from app.api.crm_automation import compile_rules
from app.api.healthcare_privacy import encrypt, decrypt

def test_crm_automation_and_healthcare_routes_registered():
    paths=set(app.openapi()["paths"])
    for path in ["/api/v1/crm/templates","/api/v1/crm/segments","/api/v1/crm/segments/{segment_id}/preview",
        "/api/v1/crm/campaigns/{campaign_id}/schedule","/api/v1/crm/scheduler/run-due",
        "/api/v1/crm/campaigns/{campaign_id}/apply-template/{template_id}",
        "/api/v1/healthcare/patients","/api/v1/healthcare/patients/{patient_id}",
        "/api/v1/healthcare/patients/{patient_id}/access","/api/v1/healthcare/patients/{patient_id}/encounters",
        "/api/v1/healthcare/patients/{patient_id}/consents","/api/v1/healthcare/patients/{patient_id}/audit"]:
        assert path in paths
    assert CRMCommunicationTemplate.__tablename__=="crm_communication_templates"
    assert CRMAudienceSegment.__tablename__=="crm_audience_segments"
    assert CRMCampaignSchedule.__tablename__=="crm_campaign_schedules"
    assert HealthcarePatient.__tablename__=="healthcare_patients"
    assert HealthcareEncounter.__tablename__=="healthcare_encounters"
    assert HealthcarePatientAccess.__tablename__=="healthcare_patient_access"
    assert HealthcareConsent.__tablename__=="healthcare_consents"
    assert HealthcareAccessAudit.__tablename__=="healthcare_access_audits"

def test_segment_rule_allowlist_rejects_unsafe_fields_and_operators():
    clauses=compile_rules({"all":[{"field":"company","op":"contains","value":"clinic"}]})
    assert len(clauses)==1
    with pytest.raises(HTTPException):
        compile_rules({"all":[{"field":"password_hash","op":"eq","value":"x"}]})
    with pytest.raises(HTTPException):
        compile_rules({"any":[{"field":"email","op":"raw_sql","value":"x"}]})

def test_healthcare_phi_is_encrypted_and_key_required(monkeypatch):
    monkeypatch.setattr(settings,"healthcare_phi_encryption_key",Fernet.generate_key().decode())
    original={"diagnosis":"private","patient_name":"Example"}
    encrypted=encrypt(original)
    assert "private" not in encrypted
    assert decrypt(encrypted)==original
    monkeypatch.setattr(settings,"healthcare_phi_encryption_key","")
    with pytest.raises(HTTPException) as exc: encrypt(original)
    assert exc.value.status_code==503
