from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from cryptography.fernet import Fernet
import pytest
from fastapi import HTTPException
from app.main import app
from app.core.config import settings
from app.core.models import (CRMCampaignTemplate, CRMContactSegment, HealthcarePatient,
    HealthcareAccessGrant, HealthcareConsent, HealthcareBreakGlass, HealthcareAccessAudit)
from app.services.crm_audience import validate_segment_definition, apply_segment, render_template_text
from app.services.healthcare_crypto import encrypt_identifier, decrypt_identifier, patient_number_digest
from app.api.healthcare_privacy import _require_role, CLINICAL_ROLES


def test_crm_automation_models_and_routes_registered():
    assert CRMCampaignTemplate.__tablename__ == "crm_campaign_templates"
    assert CRMContactSegment.__tablename__ == "crm_contact_segments"
    paths=set(app.openapi()["paths"])
    assert "/api/v1/crm/templates" in paths
    assert "/api/v1/crm/segments" in paths
    assert "/api/v1/crm/campaigns/{campaign_id}/schedule" in paths
    assert "/api/v1/crm/scheduler/run" in paths


def test_segment_definition_validates_allowed_fields_and_operators():
    definition={"all":[{"field":"company","op":"contains","value":"Health"}],
                "any":[{"field":"lead_stage","op":"in","value":["qualified","proposal"]}]}
    assert validate_segment_definition(definition)==definition
    with pytest.raises(ValueError):
        validate_segment_definition({"all":[{"field":"password","op":"eq","value":"x"}]})
    with pytest.raises(ValueError):
        validate_segment_definition({"all":[{"field":"email","op":"raw_sql","value":"x"}]})


def test_segment_query_compiles_without_interpolating_user_sql():
    from app.core.models import CRMContact
    from sqlalchemy import select
    q=apply_segment(select(CRMContact),{"all":[{"field":"company","op":"contains","value":"%' OR 1=1 --"}]})
    sql=str(q.compile(compile_kwargs={"literal_binds":False}))
    assert "crm_contacts.company" in sql
    assert "OR 1=1" not in sql


def test_template_personalization_uses_allowlisted_fields():
    contact=SimpleNamespace(full_name="Jane Doe",company="Acme",email="jane@example.test",phone="254700000000")
    assert render_template_text("Hi {{first_name}} at {{company}}",contact)=="Hi Jane at Acme"
    with pytest.raises(ValueError):
        render_template_text("{{password}}",contact)


def test_healthcare_models_and_routes_registered():
    assert HealthcarePatient.__tablename__=="healthcare_patients"
    assert HealthcareAccessGrant.__tablename__=="healthcare_access_grants"
    assert HealthcareConsent.__tablename__=="healthcare_consents"
    assert HealthcareBreakGlass.__tablename__=="healthcare_break_glass"
    assert HealthcareAccessAudit.__tablename__=="healthcare_access_audits"
    paths=set(app.openapi()["paths"])
    assert "/api/v1/healthcare/patients/{patient_id}" in paths
    assert "/api/v1/healthcare/patients/{patient_id}/access-grants" in paths
    assert "/api/v1/healthcare/patients/{patient_id}/break-glass" in paths
    assert "/api/v1/healthcare/access-audit" in paths


def test_healthcare_identifier_encryption_and_keyed_patient_number_hash(monkeypatch):
    key=Fernet.generate_key().decode()
    monkeypatch.setattr(settings,"healthcare_data_encryption_key",key)
    cipher=encrypt_identifier("Jane Doe")
    assert cipher!="Jane Doe"
    assert decrypt_identifier(cipher)=="Jane Doe"
    assert patient_number_digest("PAT-100")==patient_number_digest(" pat-100 ")
    assert patient_number_digest("PAT-100")!="PAT-101"


def test_healthcare_encryption_fails_closed_without_key(monkeypatch):
    monkeypatch.setattr(settings,"healthcare_data_encryption_key","")
    with pytest.raises(HTTPException) as exc:
        encrypt_identifier("Sensitive patient name")
    assert exc.value.status_code==503


def test_healthcare_role_gate_denies_unassigned_roles():
    with pytest.raises(HTTPException) as exc:
        _require_role(SimpleNamespace(role="sales"),CLINICAL_ROLES)
    assert exc.value.status_code==403
    _require_role(SimpleNamespace(role="doctor"),CLINICAL_ROLES)
