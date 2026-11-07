import pytest
from fastapi import HTTPException

from app.api.platform_programme import DOMAINS, TRANSITIONS, _validate_config


def test_programme_registry_covers_all_requested_workstreams():
    assert {"security", "subscriptions", "cms", "bi", "operations"} == set(DOMAINS)
    assert "sso_connection" in DOMAINS["security"]
    assert "subscription" in DOMAINS["subscriptions"]
    assert "cms_content" in DOMAINS["cms"]
    assert "dashboard_definition" in DOMAINS["bi"]
    assert "backup_policy" in DOMAINS["operations"]


def test_security_policy_rejects_unrecoverable_mfa_configuration():
    with pytest.raises(HTTPException) as exc:
        _validate_config("security_policy", {"mfa_required": True})
    assert exc.value.status_code == 422


def test_security_policy_validates_session_timeout():
    with pytest.raises(HTTPException):
        _validate_config("security_policy", {"session_idle_minutes": 0})


def test_subscription_plan_rejects_negative_price_and_unknown_currency():
    with pytest.raises(HTTPException):
        _validate_config("subscription_plan", {"amount_minor": -1})
    with pytest.raises(HTTPException):
        _validate_config("subscription_plan", {"currency": "XYZ"})


def test_integration_credentials_must_not_be_stored_in_config():
    with pytest.raises(HTTPException) as exc:
        _validate_config("integration", {"client_secret": "plaintext"})
    assert exc.value.status_code == 422


def test_production_integration_requires_sandbox_certification_reference():
    with pytest.raises(HTTPException) as exc:
        _validate_config("integration", {"environment": "production"})
    assert exc.value.status_code == 409
    _validate_config("integration", {
        "environment": "production",
        "certification_reference": "CERT-2026-001",
        "secret_manager_ref": "vault://onecore/provider-a",
    })


def test_bi_definitions_validate_metric_identifiers():
    with pytest.raises(HTTPException):
        _validate_config("dashboard_definition", {"metrics": ["revenue", ""]})
    _validate_config("report_definition", {"metrics": ["revenue", "gross_margin"]})


def test_lifecycle_transitions_are_explicit_and_no_direct_production_bypass():
    assert "production" not in TRANSITIONS["provider_account"]["draft"]
    assert "certified" in TRANSITIONS["provider_account"]["sandbox"]
    assert "published" not in TRANSITIONS["cms_content"]["draft"]
