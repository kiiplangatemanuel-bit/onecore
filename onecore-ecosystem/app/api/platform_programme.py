"""Tenant-scoped control plane for the platform-wide programme.

This API stores governed configuration and lifecycle records. It deliberately does
not pretend that an external provider has been certified or that a queued webhook
has been delivered; provider workers and deployment infrastructure own those
side effects.
"""
from datetime import datetime, timezone
import hashlib
import json
import re

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import AuditEvent, Record, User
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission

router = APIRouter(prefix="/api/v1/platform/programme", tags=["platform-programme"])
MODULE = "platform_programme"

DOMAINS = {
    "security": {"security_policy", "role_definition", "sso_connection", "trusted_device"},
    "subscriptions": {"subscription_plan", "subscription", "provider_account", "integration"},
    "cms": {"cms_content", "onboarding_template", "training_resource"},
    "bi": {"dashboard_definition", "report_definition", "data_quality_rule"},
    "operations": {"alert_rule", "backup_policy", "restore_drill", "release_gate"},
}
TRANSITIONS = {
    "security_policy": {"draft": {"active"}, "active": {"retired"}},
    "role_definition": {"draft": {"active"}, "active": {"retired"}},
    "sso_connection": {"draft": {"testing", "disabled"}, "testing": {"active", "disabled"}, "active": {"disabled"}, "disabled": {"testing"}},
    "trusted_device": {"pending": {"trusted", "revoked"}, "trusted": {"revoked"}},
    "subscription_plan": {"draft": {"published"}, "published": {"retired"}},
    "subscription": {"trial": {"active", "grace", "suspended"}, "active": {"grace", "suspended", "cancelled"}, "grace": {"active", "suspended", "cancelled"}, "suspended": {"active", "cancelled"}},
    "provider_account": {"draft": {"sandbox", "disabled"}, "sandbox": {"certified", "disabled"}, "certified": {"production", "disabled"}, "production": {"disabled"}, "disabled": {"sandbox"}},
    "integration": {"draft": {"sandbox", "disabled"}, "sandbox": {"certified", "disabled"}, "certified": {"active", "disabled"}, "active": {"rotating", "disabled"}, "rotating": {"active", "disabled"}, "disabled": {"sandbox"}},
    "cms_content": {"draft": {"review"}, "review": {"approved", "draft"}, "approved": {"published", "draft"}, "published": {"archived"}},
    "onboarding_template": {"draft": {"published"}, "published": {"retired"}},
    "training_resource": {"draft": {"review"}, "review": {"published", "draft"}, "published": {"retired"}},
    "dashboard_definition": {"draft": {"published"}, "published": {"retired"}},
    "report_definition": {"draft": {"published"}, "published": {"retired"}},
    "data_quality_rule": {"draft": {"active"}, "active": {"disabled"}, "disabled": {"active"}},
    "alert_rule": {"draft": {"active"}, "active": {"disabled"}, "disabled": {"active"}},
    "backup_policy": {"draft": {"active"}, "active": {"disabled"}, "disabled": {"active"}},
    "restore_drill": {"planned": {"running", "cancelled"}, "running": {"passed", "failed"}, "failed": {"planned"}},
    "release_gate": {"draft": {"ready", "blocked"}, "ready": {"accepted", "blocked"}, "blocked": {"draft"}, "accepted": {"retired"}},
}

class ResourceIn(BaseModel):
    key: str = Field(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    name: str = Field(min_length=2, max_length=180)
    config: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)

class TransitionIn(BaseModel):
    status: str = Field(min_length=2, max_length=30)
    reason: str = Field(min_length=3, max_length=1000)

def _now():
    return datetime.now(timezone.utc).isoformat()

def _audit(db, user_id, org_id, action, record_id, detail):
    db.add(AuditEvent(actor_user_id=user_id, organization_id=org_id, action=action,
                      resource_type="platform_programme", resource_id=str(record_id), detail=detail))

def _validate_config(kind, config):
    if not isinstance(config, dict):
        raise HTTPException(422, "config must be an object")
    if kind == "security_policy":
        if config.get("mfa_required") and not config.get("recovery_method"):
            raise HTTPException(422, "MFA policy must define a recovery method")
        if config.get("session_idle_minutes") is not None and not 1 <= int(config["session_idle_minutes"]) <= 1440:
            raise HTTPException(422, "session_idle_minutes must be between 1 and 1440")
    if kind == "subscription_plan":
        if config.get("currency", "KES") not in {"KES", "USD", "EUR", "GBP"}:
            raise HTTPException(422, "Unsupported plan currency")
        if "amount_minor" in config and int(config["amount_minor"]) < 0:
            raise HTTPException(422, "Plan amount cannot be negative")
    if kind == "integration":
        if config.get("environment", "sandbox") not in {"sandbox", "production"}:
            raise HTTPException(422, "Integration environment must be sandbox or production")
        if config.get("environment") == "production" and not config.get("certification_reference"):
            raise HTTPException(409, "Production integrations require a certification reference")
        # Secret material must be held in a secret manager, never in JSON config.
        forbidden = {"secret", "client_secret", "password", "private_key", "access_token", "api_secret"}
        def contains_secret_key(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized = str(key).lower()
                    if normalized in forbidden or (normalized.endswith("_secret") and normalized != "secret_manager_ref"):
                        return True
                    if contains_secret_key(child):
                        return True
            elif isinstance(value, list):
                return any(contains_secret_key(child) for child in value)
            return False
        if contains_secret_key(config):
            raise HTTPException(422, "Do not store credentials in config; use a secret-manager reference")
    if kind in {"dashboard_definition", "report_definition"}:
        metrics = config.get("metrics", [])
        if not isinstance(metrics, list) or len(metrics) > 100:
            raise HTTPException(422, "metrics must be a list of at most 100 entries")
        if any(not isinstance(x, str) or not x.strip() for x in metrics):
            raise HTTPException(422, "Every metric must be a non-empty identifier")

@router.get("/domains")
def programme_domains(membership=Depends(active_membership)):
    require_permission(membership, "read")
    return {domain: sorted(kinds) for domain, kinds in DOMAINS.items()}

@router.post("/{domain}/{kind}", status_code=201)
def create_resource(domain: str, kind: str, payload: ResourceIn,
                    membership=Depends(active_membership), user: User=Depends(current_user),
                    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    if domain not in DOMAINS or kind not in DOMAINS[domain]:
        raise HTTPException(404, "Unknown platform programme resource")
    _validate_config(kind, payload.config)
    exists = db.query(Record).filter_by(organization_id=membership.organization_id,
        module_key=MODULE, record_type=kind).all()
    if any((x.data or {}).get("key") == payload.key for x in exists):
        raise HTTPException(409, "Resource key already exists in this organization")
    initial = "pending" if kind == "trusted_device" else ("planned" if kind == "restore_drill" else "draft")
    data = {"key": payload.key, "name": payload.name, "config": payload.config,
            "metadata": payload.metadata, "status": initial, "created_at": _now(),
            "updated_at": _now(), "version": 1}
    row = Record(organization_id=membership.organization_id, module_key=MODULE,
                 record_type=kind, data=data, created_by=user.id)
    db.add(row)
    db.flush()
    _audit(db, user.id, membership.organization_id, f"platform.{kind}.created", row.id, payload.key)
    db.commit()
    return {"id": row.id, **data}

@router.get("/{domain}/{kind}")
def list_resources(domain: str, kind: str, membership=Depends(active_membership),
                   db: Session=Depends(get_db)):
    require_permission(membership, "read")
    if domain not in DOMAINS or kind not in DOMAINS[domain]:
        raise HTTPException(404, "Unknown platform programme resource")
    rows = db.query(Record).filter_by(organization_id=membership.organization_id,
        module_key=MODULE, record_type=kind).order_by(Record.id.desc()).all()
    return [{"id": x.id, **(x.data or {})} for x in rows]

@router.post("/{domain}/{kind}/{resource_id}/transition")
def transition_resource(domain: str, kind: str, resource_id: int, payload: TransitionIn,
                        membership=Depends(active_membership), user: User=Depends(current_user),
                        db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    if domain not in DOMAINS or kind not in DOMAINS[domain]:
        raise HTTPException(404, "Unknown platform programme resource")
    row = db.query(Record).filter_by(id=resource_id, organization_id=membership.organization_id,
        module_key=MODULE, record_type=kind).with_for_update().first()
    if not row:
        raise HTTPException(404, "Resource not found")
    data = dict(row.data or {})
    current = data.get("status", "draft")
    allowed = TRANSITIONS.get(kind, {}).get(current, set())
    if payload.status not in allowed:
        raise HTTPException(409, f"Invalid {kind} transition: {current} -> {payload.status}")
    if kind in {"cms_content", "training_resource"} and payload.status in {"approved", "published"}:
        if row.created_by == user.id:
            raise HTTPException(403, "A different user must approve or publish content created by this user")
    if kind == "provider_account" and payload.status == "production" and not data.get("config", {}).get("certification_reference"):
        raise HTTPException(409, "Provider sandbox certification is required before production")
    if kind == "integration" and payload.status == "active":
        cfg = data.get("config", {})
        if cfg.get("environment") == "production" and not cfg.get("certification_reference"):
            raise HTTPException(409, "Production integration certification is required")
    data["status"] = payload.status
    data["updated_at"] = _now()
    data["version"] = int(data.get("version", 1)) + 1
    data.setdefault("history", []).append({"from": current, "to": payload.status,
        "actor_id": user.id, "reason": payload.reason, "at": _now()})
    row.data = data
    _audit(db, user.id, membership.organization_id, f"platform.{kind}.transitioned",
           row.id, f"{current}->{payload.status}: {payload.reason}")
    db.commit()
    return {"id": row.id, "status": payload.status, "version": data["version"]}

@router.post("/webhooks/{kind}/enqueue", status_code=202)
def enqueue_webhook(kind: str, payload: dict=Body(...),
                    idempotency_key: str=Header(alias="Idempotency-Key", min_length=8, max_length=100),
                    membership=Depends(active_membership), user: User=Depends(current_user),
                    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{1,49}", kind):
        raise HTTPException(422, "Invalid webhook event kind")
    existing = db.query(Record).filter_by(organization_id=membership.organization_id,
        module_key=MODULE, record_type="webhook_delivery").all()
    for item in existing:
        if (item.data or {}).get("idempotency_key") == idempotency_key:
            return {"id": item.id, "status": item.data["status"], "duplicate": True}
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    row = Record(organization_id=membership.organization_id, module_key=MODULE,
        record_type="webhook_delivery", created_by=user.id,
        data={"event_kind": kind, "payload": payload, "payload_sha256": hashlib.sha256(body.encode()).hexdigest(),
              "idempotency_key": idempotency_key, "status": "queued", "attempts": 0,
              "max_attempts": 8, "created_at": _now(), "next_attempt_at": _now()})
    db.add(row); db.flush()
    _audit(db, user.id, membership.organization_id, "platform.webhook.queued", row.id, kind)
    db.commit()
    return {"id": row.id, "status": "queued", "duplicate": False}

@router.get("/webhooks/deliveries")
def list_webhook_deliveries(membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    rows = db.query(Record).filter_by(organization_id=membership.organization_id,
        module_key=MODULE, record_type="webhook_delivery").order_by(Record.id.desc()).limit(200).all()
    return [{"id": r.id, **{k:v for k,v in (r.data or {}).items() if k != "payload"}} for r in rows]
