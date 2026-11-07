from app.core.models import CRMCampaignDelivery
from app.core.config import settings
from app.services.crm_delivery import send_campaign_message
from app.main import app
from fastapi import HTTPException
import pytest

def test_campaign_delivery_routes_and_model():
    assert CRMCampaignDelivery.__tablename__=="crm_campaign_deliveries"
    paths=set(app.openapi()["paths"])
    assert "/api/v1/crm/campaigns/{campaign_id}/dispatch" in paths
    assert "/api/v1/crm/campaigns/{campaign_id}/report" in paths
    assert "/api/v1/crm/delivery-events" in paths
    assert "/api/v1/crm/unsubscribe/{token}" in paths

def test_email_provider_must_be_configured(monkeypatch):
    monkeypatch.setattr(settings,"integration_email_enabled",False)
    with pytest.raises(HTTPException) as exc: send_campaign_message("email","x@y.test","s","m","key")
    assert exc.value.status_code==503

def test_unknown_channel_is_rejected():
    with pytest.raises(HTTPException) as exc: send_campaign_message("fax","x","s","m","key")
    assert exc.value.status_code==422
