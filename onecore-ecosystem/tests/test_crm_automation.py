from types import SimpleNamespace
from datetime import datetime, timezone, timedelta
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from app.core.models import CRMMessageTemplate, CRMAudienceSegment, CRMCampaignSchedule, CRMCampaignRecipient
from app.core.automation_healthcare_schemas import CRMTemplateIn, CRMSegmentIn, CRMCampaignScheduleIn
from app.services.crm_automation import validate_segment_filters, matches_segment
from app.services.crm_scheduler import render_message
from app.main import app


def test_crm_automation_models_and_routes_are_registered():
    assert CRMMessageTemplate.__tablename__=="crm_message_templates"
    assert CRMAudienceSegment.__tablename__=="crm_audience_segments"
    assert CRMCampaignSchedule.__tablename__=="crm_campaign_schedules"
    assert hasattr(CRMCampaignRecipient,"message_snapshot")
    paths=app.openapi()["paths"]
    assert "/api/v1/crm/templates" in paths
    assert "/api/v1/crm/templates/{template_id}" in paths
    assert "/api/v1/crm/segments" in paths
    assert "/api/v1/crm/segments/{segment_id}/preview" in paths
    assert "/api/v1/crm/campaigns/{campaign_id}/schedule" in paths
    assert "/api/v1/crm/schedules" in paths
    assert "/api/v1/crm/schedules/{schedule_id}/pause" in paths
    assert "/api/v1/crm/schedules/{schedule_id}/resume" in paths


def test_template_schema_limits_channels_and_content():
    row=CRMTemplateIn(name="Welcome",channel="email",subject="Hi {{first_name}}",body="Hello {{full_name}}")
    assert row.channel=="email"
    with pytest.raises(ValidationError):
        CRMTemplateIn(name="Invalid",channel="fax",body="x")


def test_nested_audience_filters_support_and_or_and_validate_fields():
    filters={"logic":"and","conditions":[
        {"field":"company","op":"contains","value":"health"},
        {"logic":"or","conditions":[
            {"field":"email","op":"is_set","value":True},
            {"field":"phone","op":"starts_with","value":"+254"}
        ]}
    ]}
    validate_segment_filters(filters)
    contact=SimpleNamespace(company="Healthcare Group",email=None,phone="+254700000000",full_name="Ada",)
    assert matches_segment(contact,filters)
    contact.phone="0700000000"
    assert not matches_segment(contact,filters)


def test_audience_filters_reject_unknown_fields_and_excessive_depth():
    with pytest.raises(HTTPException):
        validate_segment_filters({"field":"password","op":"eq","value":"secret"})
    node={"field":"company","op":"eq","value":"x"}
    for _ in range(5):
        node={"logic":"and","conditions":[node]}
    with pytest.raises(HTTPException):
        validate_segment_filters(node)


def test_schedule_requires_timezone_aware_datetime():
    payload=CRMCampaignScheduleIn(scheduled_at=datetime.now(timezone.utc)+timedelta(days=1))
    assert payload.recurrence=="once"
    with pytest.raises(ValidationError):
        CRMCampaignScheduleIn(scheduled_at=datetime(2026,12,1,9,0))


def test_template_rendering_is_personalized_and_rejects_unknown_variables():
    contact=SimpleNamespace(full_name="Ada Lovelace",email="ada@example.test",phone="+254700000000",company="Analytical Engines")
    assert render_message("Hello {{first_name}} at {{company}}",contact,"Launch")=="Hello Ada at Analytical Engines"
    with pytest.raises(ValueError):
        render_message("{{medical_record}}",contact,"Launch")
