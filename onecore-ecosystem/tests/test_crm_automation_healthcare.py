from datetime import datetime, timezone
from decimal import Decimal
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
    assert hasattr(HealthcareRoleAssignment,"scope_key")
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


def test_hospital_operations_models_and_routes_are_registered():
    from app.core.models import HealthcareResource, HealthcareEvent
    from app.api.healthcare_hospital import RESOURCE_TYPES, _money, _stable
    paths=set(app.openapi()["paths"])
    expected={
        "/api/v1/healthcare/wards","/api/v1/healthcare/wards/{ward_id}/rooms","/api/v1/healthcare/wards/{ward_id}/rooms",
        "/api/v1/healthcare/wards/{ward_id}/rooms","/api/v1/healthcare/rooms/{room_id}/beds",
        "/api/v1/healthcare/beds","/api/v1/healthcare/occupancy","/api/v1/healthcare/admissions",
        "/api/v1/healthcare/admissions/{admission_id}/discharge",
        "/api/v1/healthcare/admissions/{admission_id}/transfer",
        "/api/v1/healthcare/patients/{patient_id}/movement-history",
        "/api/v1/healthcare/patients/{patient_id}/observations",
        "/api/v1/healthcare/patients/{patient_id}/care-plans",
        "/api/v1/healthcare/patients/{patient_id}/nursing-tasks",
        "/api/v1/healthcare/nursing-tasks/{task_id}/complete",
        "/api/v1/healthcare/patients/{patient_id}/doctor-orders",
        "/api/v1/healthcare/doctor-orders/{order_id}/decision",
        "/api/v1/healthcare/patients/{patient_id}/treatment-plans",
        "/api/v1/healthcare/patients/{patient_id}/invoices",
        "/api/v1/healthcare/invoices/{invoice_id}/payments",
        "/api/v1/healthcare/patients/{patient_id}/invoices","/api/v1/healthcare/patients/{patient_id}/insurance/claims",\n        "/api/v1/healthcare/patients/{patient_id}/insurance/eligibility",
        "/api/v1/healthcare/patients/{patient_id}/insurance/preauthorizations",
        "/api/v1/healthcare/preauthorizations/{preauth_id}/decision",
        "/api/v1/healthcare/patients/{patient_id}/insurance/claims",
        "/api/v1/healthcare/insurance/claims/{claim_id}/settle",
        "/api/v1/healthcare/patients/{patient_id}/pharmacy/dispense",
        "/api/v1/healthcare/patients/{patient_id}/laboratory/orders",
        "/api/v1/healthcare/integrations/jobs/{job_id}/result",
        "/api/v1/healthcare/patients/{patient_id}/emergency/triage",
        "/api/v1/healthcare/emergency/{visit_id}/status",
        "/api/v1/healthcare/theatres","/api/v1/healthcare/patients/{patient_id}/procedures",
        "/api/v1/healthcare/procedures/{procedure_id}/complete",
        "/api/v1/healthcare/patients/{patient_id}/documents",
        "/api/v1/healthcare/privacy/monitor","/api/v1/healthcare/retention/policy",
        "/api/v1/healthcare/recovery/drills","/api/v1/healthcare/dashboard",
    }
    assert expected.issubset(paths)
    assert HealthcareResource.__tablename__=="healthcare_resources"
    assert HealthcareEvent.__tablename__=="healthcare_events"
    assert {"admission","bed","vital_observation","doctor_order","invoice","insurance_claim",
            "pharmacy_job","laboratory_job","emergency_visit","procedure","clinical_document"}.issubset(RESOURCE_TYPES)
    assert _money("125.50")==Decimal("125.50")
    assert _stable({"created_at":"now","amount":"2.00","nested":{"updated_at":"now","code":"X"}})=={
        "amount":"2.00","nested":{"code":"X"}}
    with pytest.raises(HTTPException): _money("-1")
    with pytest.raises(HTTPException): _money("1.001")


def test_hospital_roles_are_separated_by_workflow():
    from app.api.healthcare_privacy import ROLE_PERMISSIONS
    assert "observations.manage" in ROLE_PERMISSIONS["nurse"]
    assert "orders.manage" in ROLE_PERMISSIONS["clinician"]
    assert "pharmacy.manage" in ROLE_PERMISSIONS["pharmacist"]
    assert "lab.manage" in ROLE_PERMISSIONS["lab_technician"]
    assert "insurance.manage" in ROLE_PERMISSIONS["insurance_officer"]
    assert "recovery.manage" not in ROLE_PERMISSIONS["privacy_officer"]


def test_hospital_workspace_and_migration_are_present():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    page=root/"app"/"web"/"healthcare_hospital.html"
    migration=root/"migrations"/"versions"/"0033_healthcare_hospital_operations.py"
    assert page.exists() and migration.exists()
    html=page.read_text(encoding="utf-8")
    assert "/admissions" in html and "/occupancy" in html
    assert "X-Organization-ID" in html
    migration_text=migration.read_text(encoding="utf-8")
    assert 'down_revision = "0032_crm_forecast_attribution"' in migration_text
