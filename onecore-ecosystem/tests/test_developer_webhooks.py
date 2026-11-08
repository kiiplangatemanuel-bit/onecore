from datetime import timedelta
import hashlib
import hmac

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.models import (
    AuditEvent, DeveloperWebhookDelivery, DeveloperWebhookEndpoint,
    Membership, Organization, PortalWorkflowRecord, User,
)
from app.api import developer_webhooks as webhooks


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__, Organization.__table__, Membership.__table__,
        AuditEvent.__table__, PortalWorkflowRecord.__table__,
        DeveloperWebhookEndpoint.__table__, DeveloperWebhookDelivery.__table__,
    ])
    return engine


def _developer(db, org, role="developer"):
    user = User(email=f"{role}@example.com", full_name="Developer", password_hash="unused")
    db.add(user)
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role=role, is_active=True))
    db.flush()
    return user


def _webhook(db, org, user, events=None):
    record = PortalWorkflowRecord(
        portal_key="developers", record_type="webhook", organization_id=org.id,
        owner_user_id=user.id, visibility="private", status="active",
        payload={
            "name": "Integration",
            "endpoint_url": "https://hooks.example.com/onecore",
            "events": events or ["organization.updated"],
        },
    )
    db.add(record)
    db.flush()
    return record


def _endpoint(db, record, events=None):
    endpoint = DeveloperWebhookEndpoint(
        workflow_record_id=record.id, organization_id=record.organization_id,
        endpoint_url="https://hooks.example.com/onecore",
        events=events or ["organization.updated"],
        secret_encrypted=webhooks._encrypt("whsec_test"), active=True,
    )
    db.add(endpoint)
    db.flush()
    return endpoint


def test_webhook_activation_returns_encrypted_signing_secret_once(monkeypatch):
    engine = _db()
    monkeypatch.setattr(webhooks, "_validate_endpoint", lambda url: "hooks.example.com")
    with Session(engine) as db:
        org = Organization(name="Tenant", slug="tenant")
        db.add(org)
        db.flush()
        user = _developer(db, org)
        record = _webhook(db, org, user)
        db.commit()

        result = webhooks.activate_webhook(webhooks.WebhookActivate(workflow_record_id=record.id), user, db)
        endpoint = db.query(DeveloperWebhookEndpoint).one()
        assert result["signing_secret"].startswith("whsec_")
        assert result["signing_secret"] not in endpoint.secret_encrypted
        assert webhooks._decrypt(endpoint.secret_encrypted) == result["signing_secret"]
        with pytest.raises(HTTPException) as duplicate:
            webhooks.activate_webhook(webhooks.WebhookActivate(workflow_record_id=record.id), user, db)
        assert duplicate.value.status_code == 409
    engine.dispose()


def test_webhook_event_queue_is_idempotent_and_tenant_scoped():
    engine = _db()
    with Session(engine) as db:
        org = Organization(name="Tenant", slug="tenant")
        db.add(org)
        db.flush()
        user = _developer(db, org)
        record = _webhook(db, org, user)
        endpoint = _endpoint(db, record)
        db.commit()
        first = webhooks.queue_organization_webhook_event(
            db, org.id, "organization.updated", {"name": "Tenant"}, "evt_idempotent_123"
        )
        second = webhooks.queue_organization_webhook_event(
            db, org.id, "organization.updated", {"name": "Tenant"}, "evt_idempotent_123"
        )
        assert first["queued_deliveries"] == 1
        assert second["queued_deliveries"] == 0
        assert db.query(DeveloperWebhookDelivery).filter_by(endpoint_id=endpoint.id).count() == 1
        with pytest.raises(ValueError):
            webhooks.queue_organization_webhook_event(db, org.id, "unsupported.event", {})
    engine.dispose()


def test_webhook_delivery_signs_exact_body_and_marks_success(monkeypatch):
    engine = _db()
    monkeypatch.setattr(webhooks, "_validate_endpoint", lambda url: "hooks.example.com")
    sent = {}

    class Response:
        status_code = 204

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def post(self, url, content, headers):
            sent.update(url=url, content=content, headers=headers)
            return Response()

    monkeypatch.setattr(webhooks.httpx, "Client", Client)
    with Session(engine) as db:
        org = Organization(name="Tenant", slug="tenant")
        db.add(org)
        db.flush()
        user = _developer(db, org)
        record = _webhook(db, org, user)
        endpoint = _endpoint(db, record)
        delivery = DeveloperWebhookDelivery(
            endpoint_id=endpoint.id, organization_id=org.id,
            event_id="evt_delivery_123", event_type="organization.updated",
            payload={"id": "evt_delivery_123", "type": "organization.updated", "data": {"ok": True}},
            status="pending", attempts=0,
        )
        db.add(delivery)
        db.flush()
        result = webhooks._deliver_one(db, delivery)
        expected = hmac.new(
            b"whsec_test",
            sent["headers"]["X-OneCore-Timestamp"].encode() + b"." + sent["content"],
            hashlib.sha256,
        ).hexdigest()
        assert sent["headers"]["X-OneCore-Signature"] == "sha256=" + expected
        assert sent["headers"]["X-OneCore-Event-Id"] == "evt_delivery_123"
        assert result["status"] == "delivered"
        assert delivery.delivered_at is not None
        assert delivery.attempts == 1
    engine.dispose()


def test_webhook_delivery_retries_with_bounded_backoff(monkeypatch):
    engine = _db()
    monkeypatch.setattr(webhooks, "_validate_endpoint", lambda url: "hooks.example.com")

    class Response:
        status_code = 503

    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(webhooks.httpx, "Client", Client)
    with Session(engine) as db:
        org = Organization(name="Tenant", slug="tenant")
        db.add(org)
        db.flush()
        user = _developer(db, org)
        record = _webhook(db, org, user)
        endpoint = _endpoint(db, record)
        delivery = DeveloperWebhookDelivery(
            endpoint_id=endpoint.id, organization_id=org.id,
            event_id="evt_retry_123", event_type="organization.updated",
            payload={"id": "evt_retry_123"}, status="pending", attempts=0,
        )
        db.add(delivery)
        db.flush()
        result = webhooks._deliver_one(db, delivery)
        assert result["status"] == "pending"
        assert delivery.attempts == 1
        assert delivery.response_status == 503
        assert delivery.next_attempt_at > webhooks._now()
        delivery.attempts = webhooks.MAX_ATTEMPTS - 1
        result = webhooks._deliver_one(db, delivery)
        assert result["status"] == "failed"
        assert delivery.attempts == webhooks.MAX_ATTEMPTS
    engine.dispose()


def test_webhook_url_rejects_non_https_and_private_dns(monkeypatch):
    with pytest.raises(HTTPException):
        webhooks._validate_endpoint("http://hooks.example.com")
    monkeypatch.setattr(webhooks.socket, "getaddrinfo", lambda *args, **kwargs: [
        (2, 1, 6, "", ("127.0.0.1", 443)),
    ])
    with pytest.raises(HTTPException) as denied:
        webhooks._validate_endpoint("https://hooks.example.com")
    assert denied.value.status_code == 422


def test_webhook_test_event_is_endpoint_scoped_and_rate_limited():
    engine = _db()
    with Session(engine) as db:
        org = Organization(name="Tenant", slug="tenant")
        db.add(org)
        db.flush()
        user = _developer(db, org)
        record = _webhook(db, org, user)
        _endpoint(db, record)
        db.commit()
        queued = webhooks.send_webhook_test(record.id, user, db)
        assert queued["queued_deliveries"] == 1
        delivery = db.query(DeveloperWebhookDelivery).one()
        assert delivery.payload["data"]["test"] is True
        with pytest.raises(HTTPException) as limited:
            webhooks.send_webhook_test(record.id, user, db)
        assert limited.value.status_code == 429
    engine.dispose()


def test_webhook_configuration_update_and_deactivation_are_audited(monkeypatch):
    engine = _db()
    monkeypatch.setattr(webhooks, "_validate_endpoint", lambda url: "hooks.example.com")
    with Session(engine) as db:
        org = Organization(name="Tenant", slug="tenant")
        db.add(org)
        db.flush()
        user = _developer(db, org)
        record = _webhook(db, org, user)
        endpoint = _endpoint(db, record)
        pending = DeveloperWebhookDelivery(
            endpoint_id=endpoint.id, organization_id=org.id,
            event_id="evt_pending_123", event_type="organization.updated",
            payload={"id": "evt_pending_123"}, status="pending", attempts=0,
        )
        db.add(pending)
        db.commit()
        result = webhooks.update_webhook_endpoint(
            record.id,
            webhooks.WebhookEndpointUpdate(
                endpoint_url="https://hooks.example.com/new",
                events=["application.created"],
            ), user, db,
        )
        assert result["events"] == ["application.created"]
        assert endpoint.endpoint_url.endswith("/new")
        stopped = webhooks.deactivate_webhook_endpoint(record.id, user, db)
        assert stopped["active"] is False
        db.refresh(pending)
        assert pending.status == "failed"
        assert db.query(AuditEvent).filter(AuditEvent.action.like("developer.webhook.%")).count() >= 2
    engine.dispose()


def test_failed_webhook_delivery_can_be_retried_by_active_developer():
    engine = _db()
    with Session(engine) as db:
        org = Organization(name="Tenant", slug="tenant")
        db.add(org)
        db.flush()
        user = _developer(db, org)
        record = _webhook(db, org, user)
        endpoint = _endpoint(db, record)
        delivery = DeveloperWebhookDelivery(
            endpoint_id=endpoint.id, organization_id=org.id,
            event_id="evt_failed_123", event_type="organization.updated",
            payload={"id": "evt_failed_123"}, status="failed", attempts=8,
        )
        db.add(delivery)
        db.commit()
        result = webhooks.retry_webhook_delivery(record.id, delivery.event_id, user, db)
        assert result["status"] == "pending"
        assert delivery.attempts == 0
        assert delivery.next_attempt_at is not None
    engine.dispose()


def test_developer_application_creation_automatically_enqueues_subscribed_webhook():
    from app.api.portal_workflows import PortalRecordCreate, create_portal_record

    engine = _db()
    with Session(engine) as db:
        org = Organization(name="Tenant", slug="tenant")
        db.add(org)
        db.flush()
        user = _developer(db, org)
        webhook_record = _webhook(db, org, user, events=["application.created"])
        endpoint = _endpoint(db, webhook_record, events=["application.created"])
        db.commit()
        created = create_portal_record(
            "developers", "application",
            PortalRecordCreate(
                organization_id=org.id, visibility="organization",
                payload={"name": "Payroll integration"},
            ), user, db,
        )
        delivery = db.query(DeveloperWebhookDelivery).filter_by(
            endpoint_id=endpoint.id, event_type="application.created"
        ).one()
        assert delivery.status == "pending"
        assert delivery.payload["data"]["record_id"] == created["id"]
        assert delivery.event_id == f"evt_application_{created['id']}_created"
    engine.dispose()


def test_webhook_worker_rejects_out_of_range_batches():
    engine = _db()
    with Session(engine) as db:
        with pytest.raises(ValueError):
            webhooks.process_webhook_deliveries(db, 0)
        with pytest.raises(ValueError):
            webhooks.process_webhook_deliveries(db, 251)
    engine.dispose()


def test_webhook_routes_are_registered():
    from app.main import app
    paths = set(app.openapi()["paths"])
    assert "/api/v1/developer/webhooks/activate" in paths
    assert "/api/v1/developer/webhooks" in paths
    assert "/api/v1/developer/webhooks/{workflow_record_id}/rotate-secret" in paths
    assert "/api/v1/developer/webhooks/{workflow_record_id}/deliveries" in paths
    assert "/api/v1/developer/webhooks/{workflow_record_id}/test" in paths
    assert "/api/v1/developer/webhooks/{workflow_record_id}/deactivate" in paths


def test_webhook_migration_has_tenant_rls_and_idempotency():
    from pathlib import Path
    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0057_developer_webhooks.py"
    source = migration.read_text()
    assert 'revision = "0057_developer_webhooks"' in source
    assert 'down_revision = "0057_supabase_auth_identity"' in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "uq_developer_webhook_endpoint_event" in source
    assert "current_user = 'onecore_webhook_worker'" in source
