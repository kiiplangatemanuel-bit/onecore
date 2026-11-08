import hashlib
import hmac
import json

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


def _developer(db, org):
    user = User(email="dev@example.com", full_name="Developer", password_hash="unused")
    db.add(user)
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role="developer", is_active=True))
    db.flush()
    return user


def _webhook(db, org, user):
    record = PortalWorkflowRecord(
        portal_key="developers", record_type="webhook", organization_id=org.id,
        owner_user_id=user.id, visibility="private", status="active",
        payload={
            "name": "Integration", "endpoint_url": "https://hooks.example.com/onecore",
            "events": ["organization.updated"],
        },
    )
    db.add(record)
    db.flush()
    return record


def test_webhook_activation_returns_signing_secret_once_and_encrypts_it(monkeypatch):
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


def test_webhook_event_queue_is_idempotent_and_filters_subscribed_events(monkeypatch):
    engine = _db()
    monkeypatch.setattr(webhooks, "_validate_endpoint", lambda url: "hooks.example.com")
    with Session(engine) as db:
        org = Organization(name="Tenant", slug="tenant")
        db.add(org)
        db.flush()
        user = _developer(db, org)
        record = _webhook(db, org, user)
        db.add(DeveloperWebhookEndpoint(
            workflow_record_id=record.id, organization_id=org.id,
            secret_encrypted=webhooks._encrypt("whsec_test"), active=True,
        ))
        db.commit()
        payload = webhooks.WebhookEventCreate(
            organization_id=org.id, event_type="organization.updated",
            event_id="evt_idempotent_123", data={"name": "Tenant"},
        )
        first = webhooks.enqueue_webhook_event(payload, user, db)
        second = webhooks.enqueue_webhook_event(payload, user, db)
        assert first["queued_deliveries"] == 1
        assert second["queued_deliveries"] == 0
        assert db.query(DeveloperWebhookDelivery).count() == 1
        unsupported = webhooks.WebhookEventCreate(
            organization_id=org.id, event_type="sandbox.created", data={},
        )
        assert webhooks.enqueue_webhook_event(unsupported, user, db)["queued_deliveries"] == 0
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
        endpoint = DeveloperWebhookEndpoint(
            workflow_record_id=record.id, organization_id=org.id,
            secret_encrypted=webhooks._encrypt("whsec_test"), active=True,
        )
        db.add(endpoint)
        db.flush()
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
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def post(self, *args, **kwargs): return Response()

    monkeypatch.setattr(webhooks.httpx, "Client", Client)
    with Session(engine) as db:
        org = Organization(name="Tenant", slug="tenant")
        db.add(org)
        db.flush()
        user = _developer(db, org)
        record = _webhook(db, org, user)
        endpoint = DeveloperWebhookEndpoint(
            workflow_record_id=record.id, organization_id=org.id,
            secret_encrypted=webhooks._encrypt("whsec_test"), active=True,
        )
        db.add(endpoint)
        db.flush()
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


def test_webhook_migration_is_chained_after_developer_api_keys():
    from pathlib import Path
    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0057_developer_webhooks.py"
    source = migration.read_text()
    assert 'revision = "0057_developer_webhooks"' in source
    assert 'down_revision = "0056_developer_api_keys"' in source
    assert "developer_webhook_delivery_update" in source
