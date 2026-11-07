from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.models import CRMContact, CRMLead, CRMActivity
from app.core.schemas import CRMContactIn, CRMLeadIn, CRMActivityIn
from app.services.crm import validate_stage_transition
from app.main import app


def test_contact_contract_validates_name_and_email():
    contact = CRMContactIn(full_name="Jane Doe", email="jane@example.com")
    assert contact.full_name == "Jane Doe"
    with pytest.raises(ValidationError):
        CRMContactIn(full_name="J", email="not-an-email")


def test_lead_contract_limits_stage_and_currency():
    lead = CRMLeadIn(title="Annual service renewal", stage="qualified", currency="KES")
    assert lead.stage == "qualified"
    with pytest.raises(ValidationError):
        CRMLeadIn(title="Bad stage", stage="won't close", currency="KES")


def test_activity_requires_valid_type():
    activity = CRMActivityIn(lead_id=1, activity_type="call", subject="Discovery call")
    assert activity.activity_type == "call"
    with pytest.raises(ValidationError):
        CRMActivityIn(lead_id=1, activity_type="telepathy", subject="Contact")


def test_pipeline_stage_transitions_are_controlled():
    validate_stage_transition("new", "qualified")
    validate_stage_transition("proposal", "won")
    with pytest.raises(HTTPException) as exc:
        validate_stage_transition("won", "new")
    assert exc.value.status_code == 409


def test_crm_tables_and_routes_exist():
    assert CRMContact.__tablename__ == "crm_contacts"
    assert CRMLead.__tablename__ == "crm_leads"
    assert CRMActivity.__tablename__ == "crm_activities"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/crm/contacts" in paths
    assert "/api/v1/crm/leads" in paths
    assert "/api/v1/crm/activities" in paths
    assert "/crm" in paths


def test_crm_campaign_audience_preview_is_registered_and_read_only_contract():
    paths = app.openapi()["paths"]
    endpoint = "/api/v1/crm/campaigns/{campaign_id}/preview"
    assert endpoint in paths
    assert "get" in paths[endpoint]
    assert "post" not in paths[endpoint]
