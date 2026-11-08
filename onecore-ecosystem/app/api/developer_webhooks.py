"""Durable, signed developer webhook delivery and retry worker."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, text, create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.models import (
    AuditEvent, DeveloperWebhookDelivery, DeveloperWebhookEndpoint,
    Membership, Organization, PortalWorkflowRecord, User,
)
from app.core.security import current_user

router = APIRouter(prefix="/api/v1/developer", tags=["developer webhooks"])
MAX_ATTEMPTS = 8
MAX_BODY_BYTES = 256_000
ALLOWED_EVENTS = {
    "organization.updated", "application.created", "application.updated",
    "sandbox.created", "sandbox.updated",
}


def _now():
    return datetime.now(timezone.utc)


def _fernet():
    key = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    import base64
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt(secret: str) -> str:
    return _fernet().encrypt(secret.encode("utf-8")).decode("ascii")


def _decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        raise RuntimeError("Webhook signing secret cannot be decrypted; check SECRET_KEY continuity")


def _active_developer(db: Session, user: User, organization_id: int):
    membership = db.query(Membership).filter_by(
        user_id=user.id, organization_id=organization_id, is_active=True
    ).first()
    if not membership or membership.role not in {"org_admin", "developer"}:
        raise HTTPException(404, "Webhook not found")
    return membership


def _validate_endpoint(url: str):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(422, "Webhook destination must be an HTTPS URL without embedded credentials")
    if parsed.port not in (None, 443):
        raise HTTPException(422, "Webhook destination must use the standard HTTPS port")
    if len(url) > 2048 or parsed.fragment:
        raise HTTPException(422, "Webhook destination URL is invalid")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal")):
        raise HTTPException(422, "Private and local webhook destinations are not allowed")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError:
        raise HTTPException(422, "Webhook destination hostname could not be resolved")
    if not addresses:
        raise HTTPException(422, "Webhook destination hostname has no addresses")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not ip.is_global:
            raise HTTPException(422, "Webhook destinations must resolve only to public IP addresses")
    return host


class WebhookActivate(BaseModel):
    workflow_record_id: int = Field(gt=0)


class WebhookEventCreate(BaseModel):
    organization_id: int = Field(gt=0)
    event_type: str = Field(min_length=3, max_length=120)
    event_id: str | None = Field(default=None, min_length=8, max_length=80)
    data: dict = Field(default_factory=dict)


@router.post('/webhooks/activate')
def activate_webhook(
    payload: WebhookActivate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    record = db.query(PortalWorkflowRecord).filter_by(
        id=payload.workflow_record_id, portal_key="developers",
        record_type="webhook",
    ).first()
    if not record:
        raise HTTPException(404, "Webhook not found")
    _active_developer(db, user, record.organization_id)
    endpoint_url = str((record.payload or {}).get("endpoint_url", ""))
    events = (record.payload or {}).get("events", [])
    _validate_endpoint(endpoint_url)
    if not isinstance(events, list) or not events or set(events) - ALLOWED_EVENTS:
        raise HTTPException(422, "Webhook must subscribe to supported event types")
    endpoint = db.query(DeveloperWebhookEndpoint).filter_by(workflow_record_id=record.id).first()
    if endpoint and endpoint.active:
        raise HTTPException(409, "Webhook is already activated; rotate its signing secret instead")
    secret = "whsec_" + secrets.token_urlsafe(36)
    if endpoint:
        endpoint.secret_encrypted = _encrypt(secret)
        endpoint.endpoint_url = endpoint_url
        endpoint.events = sorted(set(events))
        endpoint.active = True
        endpoint.rotated_at = _now()
    else:
        endpoint = DeveloperWebhookEndpoint(
            workflow_record_id=record.id, organization_id=record.organization_id,
            endpoint_url=endpoint_url, events=sorted(set(events)),
            secret_encrypted=_encrypt(secret), active=True,
        )
        db.add(endpoint)
    db.add(AuditEvent(
        actor_user_id=user.id, organization_id=record.organization_id,
        action="developer.webhook.activated", resource_type="developer_webhook",
        resource_id=str(record.id), detail="Signing secret issued once",
    ))
    db.commit()
    db.refresh(endpoint)
    return {"endpoint_id": endpoint.id, "active": True, "signing_secret": secret}


@router.post('/webhooks/{workflow_record_id}/rotate-secret')
def rotate_webhook_secret(
    workflow_record_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    record = db.query(PortalWorkflowRecord).filter_by(
        id=workflow_record_id, portal_key="developers", record_type="webhook"
    ).first()
    if not record:
        raise HTTPException(404, "Webhook not found")
    _active_developer(db, user, record.organization_id)
    endpoint = db.query(DeveloperWebhookEndpoint).filter_by(
        workflow_record_id=record.id, active=True
    ).with_for_update().first()
    if not endpoint:
        raise HTTPException(404, "Active webhook not found")
    secret = "whsec_" + secrets.token_urlsafe(36)
    endpoint.secret_encrypted = _encrypt(secret)
    endpoint.rotated_at = _now()
    db.add(AuditEvent(
        actor_user_id=user.id, organization_id=record.organization_id,
        action="developer.webhook.secret_rotated", resource_type="developer_webhook",
        resource_id=str(record.id), detail="Signing secret rotated",
    ))
    db.commit()
    return {"endpoint_id": endpoint.id, "signing_secret": secret}


def queue_organization_webhook_event(
    db: Session, organization_id: int, event_type: str, data: dict,
    event_id: str | None = None,
) -> dict:
    """Enqueue a domain event from a trusted backend workflow in the current transaction."""
    if event_type not in ALLOWED_EVENTS:
        raise ValueError("Unsupported webhook event type")
    if len(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > MAX_BODY_BYTES:
        raise ValueError("Webhook event payload exceeds 256 KB")
    event_id = event_id or "evt_" + secrets.token_urlsafe(24)
    endpoints = db.query(DeveloperWebhookEndpoint).join(
        PortalWorkflowRecord, PortalWorkflowRecord.id == DeveloperWebhookEndpoint.workflow_record_id
    ).filter(
        DeveloperWebhookEndpoint.organization_id == organization_id,
        DeveloperWebhookEndpoint.active.is_(True),
        PortalWorkflowRecord.portal_key == "developers",
        PortalWorkflowRecord.record_type == "webhook",
    ).all()
    created = 0
    for endpoint in endpoints:
        if event_type not in (endpoint.events or []):
            continue
        existing = db.query(DeveloperWebhookDelivery).filter_by(
            endpoint_id=endpoint.id, event_id=event_id
        ).first()
        if existing:
            continue
        db.add(DeveloperWebhookDelivery(
            endpoint_id=endpoint.id, organization_id=organization_id,
            event_id=event_id, event_type=event_type,
            payload={"id": event_id, "type": event_type, "created_at": _now().isoformat(), "data": data},
            status="pending", attempts=0, next_attempt_at=_now(),
        ))
        created += 1
    return {"event_id": event_id, "queued_deliveries": created}


@router.get("/webhooks")
def list_developer_webhooks(
    organization_id: int = Query(gt=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    _active_developer(db, user, organization_id)
    records = db.query(PortalWorkflowRecord).filter_by(
        portal_key="developers", record_type="webhook", organization_id=organization_id
    ).order_by(PortalWorkflowRecord.updated_at.desc()).all()
    result = []
    for record in records:
        endpoint = db.query(DeveloperWebhookEndpoint).filter_by(workflow_record_id=record.id).first()
        counts = dict(db.query(
            DeveloperWebhookDelivery.status,
            func.count(DeveloperWebhookDelivery.id),
        ).filter_by(endpoint_id=endpoint.id).group_by(DeveloperWebhookDelivery.status).all()) if endpoint else {}
        result.append({
            "workflow_record_id": record.id,
            "name": (record.payload or {}).get("name", "Webhook"),
            "endpoint_url": (record.payload or {}).get("endpoint_url", ""),
            "events": (record.payload or {}).get("events", []),
            "active": bool(endpoint and endpoint.active),
            "deliveries": counts,
        })
    return result


@router.get("/webhooks/{workflow_record_id}/deliveries")
def list_webhook_deliveries(
    workflow_record_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    record = db.query(PortalWorkflowRecord).filter_by(
        id=workflow_record_id, portal_key="developers", record_type="webhook"
    ).first()
    if not record:
        raise HTTPException(404, "Webhook not found")
    _active_developer(db, user, record.organization_id)
    endpoint = db.query(DeveloperWebhookEndpoint).filter_by(workflow_record_id=record.id).first()
    if not endpoint:
        return {"items": [], "total": 0}
    rows = db.query(DeveloperWebhookDelivery).filter_by(endpoint_id=endpoint.id).order_by(
        DeveloperWebhookDelivery.created_at.desc()
    ).limit(limit).all()
    total = db.query(DeveloperWebhookDelivery).filter_by(endpoint_id=endpoint.id).count()
    return {
        "total": total,
        "items": [{
            "event_id": row.event_id, "event_type": row.event_type,
            "status": row.status, "attempts": row.attempts,
            "response_status": row.response_status, "last_error": row.last_error,
            "created_at": row.created_at.isoformat(),
            "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
            "next_attempt_at": row.next_attempt_at.isoformat() if row.status == "pending" else None,
        } for row in rows],
    }

def _deliver_one(db: Session, delivery: DeveloperWebhookDelivery) -> dict:
    endpoint = db.query(DeveloperWebhookEndpoint).filter_by(
        id=delivery.endpoint_id, active=True
    ).first()
    if not endpoint:
        delivery.status = "failed"
        delivery.last_error = "Webhook endpoint is inactive or missing"
        return {"id": delivery.id, "status": delivery.status}
    url = endpoint.endpoint_url
    _validate_endpoint(url)
    body = json.dumps(delivery.payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    timestamp = str(int(_now().timestamp()))
    secret = _decrypt(endpoint.secret_encrypted)
    signature = hmac.new(secret.encode("utf-8"), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    delivery.attempts += 1
    try:
        with httpx.Client(timeout=httpx.Timeout(8.0, connect=3.0), follow_redirects=False, trust_env=False) as client:
            response = client.post(url, content=body, headers={
                "Content-Type": "application/json",
                "User-Agent": "OneCore-Webhooks/1.0",
                "X-OneCore-Event": delivery.event_type,
                "X-OneCore-Event-Id": delivery.event_id,
                "X-OneCore-Timestamp": timestamp,
                "X-OneCore-Signature": "sha256=" + signature,
            })
        delivery.response_status = response.status_code
        if 200 <= response.status_code < 300:
            delivery.status = "delivered"
            delivery.delivered_at = _now()
            delivery.last_error = ""
        else:
            raise RuntimeError(f"Destination returned HTTP {response.status_code}")
    except Exception as exc:
        delivery.last_error = str(exc)[:500]
        if delivery.attempts >= MAX_ATTEMPTS:
            delivery.status = "failed"
        else:
            delivery.status = "pending"
            delivery.next_attempt_at = _now() + timedelta(seconds=min(3600, 15 * (2 ** (delivery.attempts - 1))))
    return {"id": delivery.id, "status": delivery.status, "attempts": delivery.attempts}


def process_webhook_deliveries(db: Session, limit: int = 25) -> list[dict]:
    """Worker entry point. A trusted worker sets its RLS bypass flag transaction-locally."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT set_config('app.webhook_worker', 'true', true)"))
    rows = db.query(DeveloperWebhookDelivery).filter(
        DeveloperWebhookDelivery.status == "pending",
        DeveloperWebhookDelivery.next_attempt_at <= _now(),
    ).order_by(DeveloperWebhookDelivery.next_attempt_at).with_for_update(skip_locked=True).limit(limit).all()
    results = []
    for row in rows:
        try:
            if db.bind is not None and db.bind.dialect.name == "postgresql":
                db.execute(text("SELECT set_config('app.webhook_worker', 'true', true)"))
            results.append(_deliver_one(db, row))
        except Exception as exc:
            row.attempts += 1
            row.last_error = str(exc)[:500]
            row.status = "failed" if row.attempts >= MAX_ATTEMPTS else "pending"
            row.next_attempt_at = _now() + timedelta(seconds=min(3600, 15 * (2 ** (row.attempts - 1))))
            results.append({"id": row.id, "status": row.status, "attempts": row.attempts})
        db.commit()
    return results


def run_webhook_worker(batch_size: int = 25):
    if not 1 <= batch_size <= 250:
        raise ValueError("Webhook batch size must be between 1 and 250")
    if settings.webhook_worker_database_url:
        worker_engine = create_engine(settings.webhook_worker_database_url, pool_pre_ping=True)
        try:
            from sqlalchemy.orm import sessionmaker
            worker_session = sessionmaker(bind=worker_engine, expire_on_commit=False)
            with worker_session() as db:
                return process_webhook_deliveries(db, batch_size)
        finally:
            worker_engine.dispose()
    with SessionLocal() as db:
        return process_webhook_deliveries(db, batch_size)
