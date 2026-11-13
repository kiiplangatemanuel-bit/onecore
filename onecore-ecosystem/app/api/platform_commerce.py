"""Tenant-scoped subscription lifecycle and private document storage APIs."""
import hashlib
import json
import secrets
import socket
import struct
import uuid
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

import boto3
from botocore.config import Config
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.models import AuditEvent, Organization, User
from app.core.platform_commerce_models import (
    ManagedFile, ManagedFileShare, ManagedFileVersion, OrganizationSubscription, SubscriptionPayment, SubscriptionPlan,
)
from app.core.security import current_user, require_platform_admin
from app.core.tenancy import active_membership
from app.core.authorization import require_permission

router = APIRouter(prefix="/api/v1", tags=["platform commerce and files"])
MAX_FILE_BYTES = 20 * 1024 * 1024


class SubscriptionStartIn(BaseModel):
    plan_id: int = Field(gt=0)
    auto_renew: bool = False


class SubscriptionPaymentIn(BaseModel):
    method: Literal["mpesa", "bank_transfer", "card", "cash"]
    external_reference: str = Field(min_length=4, max_length=120)
    idempotency_key: str = Field(min_length=12, max_length=100)


class FolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_id: int | None = Field(default=None, gt=0)


class FileMoveIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_id: int | None = Field(default=None, gt=0)


class ShareIn(BaseModel):
    expires_in_hours: int = Field(default=24, ge=1, le=720)
    max_downloads: int = Field(default=1, ge=1, le=100)


def _utc():
    return datetime.now(timezone.utc)


def _add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return value.replace(year=year, month=month, day=min(value.day, monthrange(year, month)[1]))


def _audit(db, user_id, organization_id, action, resource_type, resource_id, detail=""):
    db.add(AuditEvent(actor_user_id=user_id, organization_id=organization_id, action=action,
                      resource_type=resource_type, resource_id=str(resource_id), detail=detail))


def _plan_out(row):
    return {"id": row.id, "code": row.code, "name": row.name, "description": row.description,
            "amount": str(row.amount), "currency": row.currency, "interval": row.interval,
            "entitlements": row.entitlements or {}, "is_active": row.is_active}


def _subscription_out(row, plan=None):
    return {"id": row.id, "organization_id": row.organization_id, "plan_id": row.plan_id,
            "plan": _plan_out(plan) if plan else None, "status": row.status,
            "starts_at": row.starts_at.isoformat() if row.starts_at else None,
            "ends_at": row.ends_at.isoformat() if row.ends_at else None,
            "auto_renew": row.auto_renew, "created_at": row.created_at.isoformat()}


@router.get("/subscription-plans")
def list_subscription_plans(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_plan_out(x) for x in db.query(SubscriptionPlan).filter_by(is_active=True).order_by(SubscriptionPlan.amount).all()]


@router.get("/subscriptions/current")
def current_subscription(membership=Depends(active_membership), db: Session = Depends(get_db)):
    rows = db.query(OrganizationSubscription).filter_by(organization_id=membership.organization_id).order_by(
        OrganizationSubscription.created_at.desc()).limit(10).all()
    result = []
    for row in rows:
        result.append(_subscription_out(row, db.get(SubscriptionPlan, row.plan_id)))
    return result


@router.post("/subscriptions", status_code=201)
def start_subscription(payload: SubscriptionStartIn, membership=Depends(active_membership),
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    if membership.role != "org_admin":
        raise HTTPException(403, "Organization administrator role required")
    plan = db.query(SubscriptionPlan).filter_by(id=payload.plan_id, is_active=True).first()
    if not plan:
        raise HTTPException(404, "Subscription plan not found")
    active = db.query(OrganizationSubscription).filter(
        OrganizationSubscription.organization_id == membership.organization_id,
        OrganizationSubscription.status.in_(["pending_payment", "active", "trialing", "past_due"])
    ).first()
    if active:
        raise HTTPException(409, "An active or pending subscription already exists; contact OneCore to change plans")
    row = OrganizationSubscription(organization_id=membership.organization_id, plan_id=plan.id,
                                    status="pending_payment", auto_renew=payload.auto_renew, created_by=user.id)
    db.add(row); db.flush()
    _audit(db, user.id, membership.organization_id, "subscription.started", "subscription", row.id,
           f"plan={plan.code};status=pending_payment")
    db.commit(); db.refresh(row)
    return _subscription_out(row, plan)


@router.get("/subscriptions/payments")
def list_subscription_payments(membership=Depends(active_membership), db: Session = Depends(get_db)):
    rows = db.query(SubscriptionPayment).filter_by(organization_id=membership.organization_id).order_by(
        SubscriptionPayment.created_at.desc()).limit(100).all()
    return [{"id": x.id, "subscription_id": x.subscription_id, "amount": str(x.amount),
             "currency": x.currency, "method": x.method, "external_reference": x.external_reference,
             "status": x.status, "review_note": x.review_note, "created_at": x.created_at.isoformat(),
             "verified_at": x.verified_at.isoformat() if x.verified_at else None} for x in rows]


@router.post("/subscriptions/{subscription_id}/payments", status_code=201)
def submit_subscription_payment(subscription_id: int, payload: SubscriptionPaymentIn,
                                 membership=Depends(active_membership), user: User = Depends(current_user),
                                 db: Session = Depends(get_db)):
    if membership.role != "org_admin":
        raise HTTPException(403, "Organization administrator role required")
    subscription = db.query(OrganizationSubscription).filter_by(
        id=subscription_id, organization_id=membership.organization_id, status="pending_payment"
    ).first()
    if not subscription:
        raise HTTPException(404, "Pending subscription not found")
    plan = db.get(SubscriptionPlan, subscription.plan_id)
    fingerprint = hashlib.sha256(json.dumps({
        "subscription_id": subscription.id, "method": payload.method,
        "reference": payload.external_reference.strip().upper(), "amount": str(plan.amount),
        "currency": plan.currency,
    }, sort_keys=True).encode()).hexdigest()
    existing = db.query(SubscriptionPayment).filter_by(
        organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
    ).first()
    if existing:
        if existing.request_hash != fingerprint:
            raise HTTPException(409, "Idempotency key was already used with different payment details")
        return {"id": existing.id, "status": existing.status, "idempotent_replay": True}
    row = SubscriptionPayment(
        organization_id=membership.organization_id, subscription_id=subscription.id,
        amount=plan.amount, currency=plan.currency, method=payload.method,
        external_reference=payload.external_reference.strip(), idempotency_key=payload.idempotency_key,
        request_hash=fingerprint, status="pending_verification", created_by=user.id,
    )
    db.add(row); db.flush()
    _audit(db, user.id, membership.organization_id, "subscription.payment_submitted", "subscription_payment",
           row.id, f"method={row.method};reference={row.external_reference}")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Duplicate payment request")
    db.refresh(row)
    return {"id": row.id, "status": row.status, "amount": str(row.amount), "currency": row.currency,
            "message": "Payment reference recorded. Subscription activates only after OneCore verifies settlement."}


def _s3():
    if not settings.integration_object_storage_enabled or not settings.s3_bucket or not settings.s3_access_key_id or not settings.s3_secret_access_key:
        raise HTTPException(503, "Private object storage is not configured on the OneCore API")
    return boto3.client("s3", endpoint_url=settings.s3_endpoint_url or None,
                        aws_access_key_id=settings.s3_access_key_id,
                        aws_secret_access_key=settings.s3_secret_access_key,
                        region_name=settings.s3_region or "auto",
                        config=Config(signature_version="s3v4"))


def _scan(data: bytes):
    if not settings.support_attachment_scanning_enabled or not settings.clamav_host:
        raise HTTPException(503, "File upload is disabled until the malware scanner is configured")
    try:
        with socket.create_connection((settings.clamav_host, settings.clamav_port),
                                      timeout=settings.clamav_timeout_seconds) as sock:
            sock.settimeout(settings.clamav_timeout_seconds)
            sock.sendall(b"zINSTREAM" + bytes([0]))
            for offset in range(0, len(data), 64 * 1024):
                chunk = data[offset:offset + 64 * 1024]
                sock.sendall(struct.pack("!I", len(chunk)) + chunk)
            sock.sendall(struct.pack("!I", 0))
            response = sock.recv(4096).decode("utf-8", "replace")
        if response.endswith("OK"):
            return
        if "FOUND" in response:
            raise HTTPException(422, "The file was blocked by malware scanning")
        raise HTTPException(503, "The malware scanner returned an inconclusive result")
    except HTTPException:
        raise
    except OSError:
        raise HTTPException(503, "The malware scanner is unavailable; file upload was not accepted")


def _file_out(row):
    return {"id": row.id, "parent_id": row.parent_id, "name": row.name, "is_folder": row.is_folder,
            "content_type": row.content_type, "size_bytes": row.size_bytes, "sha256": row.sha256,
            "classification": row.classification, "scan_status": row.scan_status,
            "created_at": row.created_at.isoformat()}


def _parent_folder(db, organization_id, parent_id):
    if parent_id is None:
        return
    row = db.query(ManagedFile).filter_by(id=parent_id, organization_id=organization_id,
                                          is_folder=True, deleted_at=None).first()
    if not row:
        raise HTTPException(404, "Parent folder not found")


@router.get("/files")
def list_files(parent_id: int | None = Query(default=None, gt=0), q: str = Query(default="", max_length=120),
               membership=Depends(active_membership), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    query = db.query(ManagedFile).filter_by(organization_id=membership.organization_id,
                                            parent_id=parent_id, deleted_at=None)
    if q.strip():
        query = query.filter(ManagedFile.name.ilike(f"%{q.strip()}%"))
    return [_file_out(x) for x in query.order_by(ManagedFile.is_folder.desc(), ManagedFile.name).limit(500).all()]


@router.post("/files/folders", status_code=201)
def create_folder(payload: FolderIn, membership=Depends(active_membership),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "create")
    _parent_folder(db, membership.organization_id, payload.parent_id)
    row = ManagedFile(organization_id=membership.organization_id, parent_id=payload.parent_id,
                      uploaded_by=user.id, name=payload.name.strip(), object_key=f"folders/{membership.organization_id}/{uuid.uuid4().hex}",
                      content_type="inode/directory", size_bytes=0, sha256=hashlib.sha256(b"").hexdigest(),
                      classification="internal", scan_status="clean", is_folder=True)
    db.add(row); db.flush()
    _audit(db, user.id, membership.organization_id, "file.folder_created", "managed_file", row.id, row.name)
    db.commit(); db.refresh(row)
    return _file_out(row)


@router.post("/files/upload", status_code=201)
async def upload_file(file: UploadFile = File(...), parent_id: int | None = Query(default=None, gt=0),
                      classification: Literal["internal", "confidential", "restricted"] = Form(default="internal"),
                      membership=Depends(active_membership), user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    require_permission(membership, "create")
    _parent_folder(db, membership.organization_id, parent_id)
    name = (file.filename or "upload").replace("\\", "/").split("/")[-1].strip()
    if not name or len(name) > 255 or any(ord(c) < 32 for c in name):
        raise HTTPException(422, "Invalid file name")
    data = await file.read(MAX_FILE_BYTES + 1)
    if not data or len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "File must be between 1 byte and 20 MB")
    _scan(data)
    key = f"organizations/{membership.organization_id}/files/{uuid.uuid4().hex}"
    digest = hashlib.sha256(data).hexdigest()
    content_type = (file.content_type or "application/octet-stream")[:160]
    client = _s3()
    try:
        client.put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type,
                          Metadata={"sha256": digest, "organization_id": str(membership.organization_id)})
    except Exception:
        raise HTTPException(502, "Private object storage rejected the upload")
    row = ManagedFile(organization_id=membership.organization_id, parent_id=parent_id, uploaded_by=user.id,
                      name=name, object_key=key, content_type=content_type, size_bytes=len(data), sha256=digest,
                      classification=classification, scan_status="clean", is_folder=False)
    db.add(row); db.flush()
    db.add(ManagedFileVersion(organization_id=membership.organization_id, file_id=row.id, version_number=1,
        uploaded_by=user.id, object_key=key, content_type=content_type, size_bytes=len(data), sha256=digest, scan_status="clean"))
    _audit(db, user.id, membership.organization_id, "file.uploaded", "managed_file", row.id,
           f"size={len(data)};sha256={digest};classification={classification};version=1")
    try:
        db.commit()
    except Exception:
        db.rollback()
        try: client.delete_object(Bucket=settings.s3_bucket, Key=key)
        except Exception: pass
        raise
    db.refresh(row)
    return _file_out(row)


@router.patch("/files/{file_id}")
def move_or_rename_file(file_id: int, payload: FileMoveIn, membership=Depends(active_membership),
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(ManagedFile).filter_by(id=file_id, organization_id=membership.organization_id,
                                          deleted_at=None).first()
    if not row:
        raise HTTPException(404, "File not found")
    _parent_folder(db, membership.organization_id, payload.parent_id)
    if row.is_folder and payload.parent_id == row.id:
        raise HTTPException(409, "A folder cannot be moved into itself")
    row.name = payload.name.strip()
    row.parent_id = payload.parent_id
    _audit(db, user.id, membership.organization_id, "file.updated", "managed_file", row.id, row.name)
    db.commit(); db.refresh(row)
    return _file_out(row)


@router.delete("/files/{file_id}", status_code=204)
def delete_file(file_id: int, membership=Depends(active_membership), user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(ManagedFile).filter_by(id=file_id, organization_id=membership.organization_id,
                                          deleted_at=None).first()
    if not row:
        raise HTTPException(404, "File not found")
    if row.is_folder and db.query(ManagedFile).filter_by(organization_id=membership.organization_id,
            parent_id=row.id, deleted_at=None).first():
        raise HTTPException(409, "Move or delete folder contents before deleting this folder")
    if not row.is_folder:
        try:
            client = _s3()
            versions = db.query(ManagedFileVersion).filter_by(file_id=row.id, organization_id=membership.organization_id).all()
            keys = {row.object_key, *(x.object_key for x in versions)}
            for key in keys:
                if key: client.delete_object(Bucket=settings.s3_bucket, Key=key)
        except Exception:
            raise HTTPException(502, "Private object storage could not delete this file and its versions")
    row.deleted_at = _utc()
    db.query(ManagedFileShare).filter_by(file_id=row.id, revoked_at=None).update({"revoked_at": _utc()})
    _audit(db, user.id, membership.organization_id, "file.deleted", "managed_file", row.id, row.name)
    db.commit()



@router.get("/files/{file_id}/versions")
def list_file_versions(file_id: int, membership=Depends(active_membership), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    row = db.query(ManagedFile).filter_by(id=file_id, organization_id=membership.organization_id, deleted_at=None).first()
    if not row or row.is_folder:
        raise HTTPException(404, "File not found")
    versions = db.query(ManagedFileVersion).filter_by(
        file_id=file_id, organization_id=membership.organization_id
    ).order_by(ManagedFileVersion.version_number.desc()).all()
    return [{"id": x.id, "version_number": x.version_number, "content_type": x.content_type,
             "size_bytes": x.size_bytes, "sha256": x.sha256, "scan_status": x.scan_status,
             "created_at": x.created_at.isoformat()} for x in versions]


@router.post("/files/{file_id}/versions", status_code=201)
async def upload_file_version(file_id: int, file: UploadFile = File(...),
                              membership=Depends(active_membership), user: User = Depends(current_user),
                              db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(ManagedFile).filter_by(id=file_id, organization_id=membership.organization_id,
                                          deleted_at=None, is_folder=False).with_for_update().first()
    if not row:
        raise HTTPException(404, "File not found")
    name = (file.filename or row.name).split("/")[-1].strip()
    if not name or len(name) > 255:
        raise HTTPException(422, "Invalid file name")
    data = await file.read(MAX_FILE_BYTES + 1)
    if not data or len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "File must be between 1 byte and 20 MB")
    _scan(data)
    client = _s3()
    key = f"organizations/{membership.organization_id}/files/{uuid.uuid4().hex}"
    digest = hashlib.sha256(data).hexdigest()
    content_type = (file.content_type or "application/octet-stream")[:160]
    try:
        client.put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type,
                          Metadata={"sha256": digest, "organization_id": str(membership.organization_id)})
    except Exception:
        raise HTTPException(502, "Private object storage rejected the new version")
    latest = db.query(ManagedFileVersion).filter_by(file_id=row.id, organization_id=membership.organization_id).order_by(
        ManagedFileVersion.version_number.desc()).first()
    version_number = (latest.version_number if latest else 0) + 1
    version = ManagedFileVersion(organization_id=membership.organization_id, file_id=row.id,
        version_number=version_number, uploaded_by=user.id, object_key=key, content_type=content_type,
        size_bytes=len(data), sha256=digest, scan_status="clean")
    db.add(version)
    row.name = name
    row.object_key = key
    row.content_type = content_type
    row.size_bytes = len(data)
    row.sha256 = digest
    row.scan_status = "clean"
    _audit(db, user.id, membership.organization_id, "file.version_uploaded", "managed_file", row.id,
           f"version={version_number};size={len(data)};sha256={digest}")
    try:
        db.commit()
    except Exception:
        db.rollback()
        try: client.delete_object(Bucket=settings.s3_bucket, Key=key)
        except Exception: pass
        raise
    return {"file_id": row.id, "version_id": version.id, "version_number": version_number,
            "name": row.name, "size_bytes": len(data), "sha256": digest, "scan_status": "clean"}


@router.get("/files/{file_id}/versions/{version_id}/download")
def download_file_version(file_id: int, version_id: int, membership=Depends(active_membership),
                          db: Session = Depends(get_db)):
    require_permission(membership, "read")
    version = db.query(ManagedFileVersion).filter_by(
        id=version_id, file_id=file_id, organization_id=membership.organization_id, scan_status="clean"
    ).first()
    if not version:
        raise HTTPException(404, "File version not found or not cleared for download")
    try:
        url = _s3().generate_presigned_url("get_object", Params={"Bucket": settings.s3_bucket,
            "Key": version.object_key}, ExpiresIn=300)
    except Exception:
        raise HTTPException(502, "Private object storage could not issue a version download link")
    return {"url": url, "expires_in": 300, "version_number": version.version_number}

@router.get("/files/{file_id}/download")
def download_file(file_id: int, membership=Depends(active_membership), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    row = db.query(ManagedFile).filter_by(id=file_id, organization_id=membership.organization_id,
                                          deleted_at=None, is_folder=False, scan_status="clean").first()
    if not row:
        raise HTTPException(404, "File not found or not cleared for download")
    try:
        url = _s3().generate_presigned_url("get_object", Params={"Bucket": settings.s3_bucket, "Key": row.object_key,
            "ResponseContentDisposition": f'attachment; filename="{row.name.replace(chr(34), "")}"'}, ExpiresIn=300)
    except Exception:
        raise HTTPException(502, "Private object storage could not issue a download link")
    return {"url": url, "expires_in": 300, "name": row.name}


@router.post("/files/{file_id}/shares", status_code=201)
def create_file_share(file_id: int, payload: ShareIn, membership=Depends(active_membership),
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(ManagedFile).filter_by(id=file_id, organization_id=membership.organization_id,
                                          deleted_at=None, is_folder=False, scan_status="clean").first()
    if not row:
        raise HTTPException(404, "File not found or not cleared for sharing")
    token = secrets.token_urlsafe(32)
    share = ManagedFileShare(organization_id=membership.organization_id, file_id=row.id, created_by=user.id,
                             token_hash=hashlib.sha256(token.encode()).hexdigest(),
                             expires_at=_utc() + timedelta(hours=payload.expires_in_hours),
                             max_downloads=payload.max_downloads)
    db.add(share); db.flush()
    _audit(db, user.id, membership.organization_id, "file.share_created", "managed_file_share", share.id, row.name)
    db.commit()
    return {"id": share.id, "token": token, "download_path": f"/api/v1/files/shared/{token}/download",
            "expires_at": share.expires_at.isoformat(), "max_downloads": share.max_downloads}


@router.get("/files/shared/{token}/download")
def download_shared_file(token: str, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    db.execute(text("SELECT set_config('app.file_share_hash', :value, true)"), {"value": token_hash})
    share = db.query(ManagedFileShare).filter_by(token_hash=token_hash, revoked_at=None).with_for_update().first()
    if not share or share.expires_at <= _utc() or share.downloads >= share.max_downloads:
        raise HTTPException(404, "Share link is invalid, expired or exhausted")
    row = db.query(ManagedFile).filter_by(id=share.file_id, organization_id=share.organization_id,
                                          deleted_at=None, is_folder=False, scan_status="clean").first()
    if not row:
        raise HTTPException(404, "Shared file is unavailable")
    try:
        url = _s3().generate_presigned_url("get_object", Params={"Bucket": settings.s3_bucket, "Key": row.object_key}, ExpiresIn=300)
    except Exception:
        raise HTTPException(502, "Private object storage could not issue a download link")
    share.downloads += 1
    db.commit()
    return {"url": url, "expires_in": 300, "name": row.name}


@router.get("/files/shares")
def list_file_shares(membership=Depends(active_membership), db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    rows = db.query(ManagedFileShare).filter_by(organization_id=membership.organization_id).order_by(
        ManagedFileShare.created_at.desc()).limit(200).all()
    return [{"id": x.id, "file_id": x.file_id, "expires_at": x.expires_at.isoformat(),
             "max_downloads": x.max_downloads, "downloads": x.downloads,
             "revoked_at": x.revoked_at.isoformat() if x.revoked_at else None} for x in rows]


@router.post("/files/shares/{share_id}/revoke")
def revoke_file_share(share_id: int, membership=Depends(active_membership), user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(ManagedFileShare).filter_by(id=share_id, organization_id=membership.organization_id).first()
    if not row:
        raise HTTPException(404, "Share not found")
    row.revoked_at = _utc()
    _audit(db, user.id, membership.organization_id, "file.share_revoked", "managed_file_share", row.id)
    db.commit()
    return {"id": row.id, "revoked": True}


@router.get("/admin/platform/subscription-payments")
def admin_subscription_payments(status: str = Query(default="pending_verification"),
                                user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    query = db.query(SubscriptionPayment)
    if status != "all":
        query = query.filter_by(status=status)
    rows = query.order_by(SubscriptionPayment.created_at.desc()).limit(500).all()
    return [{"id": x.id, "organization_id": x.organization_id, "subscription_id": x.subscription_id,
             "amount": str(x.amount), "currency": x.currency, "method": x.method,
             "external_reference": x.external_reference, "status": x.status,
             "created_at": x.created_at.isoformat()} for x in rows]


class PaymentReviewIn(BaseModel):
    decision: Literal["verified", "rejected"]
    note: str = Field(default="", max_length=500)


@router.post("/admin/platform/subscription-payments/{payment_id}/review")
def review_subscription_payment(payment_id: int, payload: PaymentReviewIn,
                                user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    payment = db.query(SubscriptionPayment).filter_by(id=payment_id).with_for_update().first()
    if not payment or payment.status != "pending_verification":
        raise HTTPException(404, "Pending subscription payment not found")
    subscription = db.query(OrganizationSubscription).filter_by(
        id=payment.subscription_id, organization_id=payment.organization_id).with_for_update().first()
    if not subscription:
        raise HTTPException(409, "Subscription record is inconsistent")
    payment.status = payload.decision
    payment.verified_by = user.id
    payment.verified_at = _utc()
    payment.review_note = payload.note.strip()
    if payload.decision == "verified":
        plan = db.get(SubscriptionPlan, subscription.plan_id)
        starts = _utc()
        subscription.status = "active"
        subscription.starts_at = starts
        subscription.ends_at = _add_months(starts, 12 if plan.interval == "yearly" else 1)
    else:
        subscription.status = "payment_rejected"
    _audit(db, user.id, payment.organization_id, "subscription.payment_reviewed",
           "subscription_payment", payment.id, f"decision={payload.decision};note={payment.review_note}")
    db.commit()
    return {"payment_id": payment.id, "payment_status": payment.status, "subscription_status": subscription.status}
