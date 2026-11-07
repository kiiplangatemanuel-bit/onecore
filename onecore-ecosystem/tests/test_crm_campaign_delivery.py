from app.core.models import CRMCampaignDelivery, CRMCampaignRecipient
from app.core.config import settings
from app.services.crm_delivery import build_unsubscribe_url, send_campaign_message
from app.main import app
from fastapi import HTTPException
import pytest


def test_campaign_delivery_routes_and_models():
    assert CRMCampaignDelivery.__tablename__=="crm_campaign_deliveries"
    assert hasattr(CRMCampaignRecipient,"claimed_at")
    paths=app.openapi()["paths"]
    assert "/api/v1/crm/campaigns/{campaign_id}/dispatch" in paths
    assert "/api/v1/crm/campaigns/{campaign_id}/report" in paths
    assert "/api/v1/crm/delivery-events" in paths
    unsubscribe=paths["/api/v1/crm/unsubscribe/{token}"]
    assert "post" in unsubscribe
    assert "get" not in unsubscribe


def test_unsubscribe_url_requires_public_https():
    with pytest.raises(HTTPException) as exc:
        build_unsubscribe_url("opaque-token","http://example.test")
    assert exc.value.status_code==503
    with pytest.raises(HTTPException):
        build_unsubscribe_url("opaque-token","")
    assert build_unsubscribe_url("opaque-token","https://crm.example.test/") == (
        "https://crm.example.test/api/v1/crm/unsubscribe/opaque-token"
    )


def test_email_provider_must_be_configured(monkeypatch):
    monkeypatch.setattr(settings,"integration_email_enabled",False)
    with pytest.raises(HTTPException) as exc:
        send_campaign_message("email","x@y.test","s","m","key")
    assert exc.value.status_code==503


def test_email_provider_adds_one_click_unsubscribe_headers(monkeypatch):
    captured={}
    class FakeSMTP:
        def __init__(self,*args,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def starttls(self): pass
        def login(self,*args): pass
        def send_message(self,message): captured["message"]=message
    monkeypatch.setattr(settings,"integration_email_enabled",True)
    monkeypatch.setattr(settings,"email_host","smtp.example.test")
    monkeypatch.setattr(settings,"email_from","updates@example.test")
    monkeypatch.setattr(settings,"email_username","")
    monkeypatch.setattr("app.services.crm_delivery.smtplib.SMTP",FakeSMTP)
    result=send_campaign_message("email","person@example.test","Update","Hello","stable-key",
        "https://crm.example.test/api/v1/crm/unsubscribe/token")
    assert result["provider_message_id"]=="stable-key"
    message=captured["message"]
    assert message["List-Unsubscribe"]=="<https://crm.example.test/api/v1/crm/unsubscribe/token>"
    assert message["List-Unsubscribe-Post"]=="List-Unsubscribe=One-Click"


def test_unknown_channel_is_rejected():
    with pytest.raises(HTTPException) as exc:
        send_campaign_message("fax","x","s","m","key")
    assert exc.value.status_code==422
