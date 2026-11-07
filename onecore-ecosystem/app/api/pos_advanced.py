"""Advanced POS device trust, offline conflict review, loyalty and operations APIs.

Provider-neutral hardware remains browser/driver mediated; this module persists
operational controls and does not pretend a browser can attest physical hardware.
"""
import hashlib
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Index, Numeric, String, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, Session

from app.core.database import Base, get_db
from app.core.models import User, POSSale, POSShift
from app.api.routes import active_membership, current_user, require_permission, can_access_branch, branch_scope_ids, audit

router = APIRouter(prefix="/api/v1/pos/advanced", tags=["POS advanced operations"])


def utcnow():
    return datetime.now(timezone.utc)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class POSDevice(Base):
    __tablename__ = "pos_devices"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    device_key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(120))
    platform: Mapped[str] = mapped_column(String(80), default="browser")
    token_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    registered_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("uq_pos_device_org_key", "organization_id", "device_key", unique=True),)


class POSSyncConflict(Base):
    __tablename__ = "pos_sync_conflicts"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("pos_devices.id"), nullable=True)
    client_transaction_id: Mapped[str] = mapped_column(String(100))
    conflict_type: Mapped[str] = mapped_column(String(32))
    client_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    server_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="open")
    resolution: Mapped[str] = mapped_column(String(24), default="")
    resolution_note: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (Index("uq_pos_conflict_transaction", "organization_id", "client_transaction_id", unique=True),)


class POSSyncEvent(Base):
    __tablename__ = "pos_sync_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("pos_devices.id"), nullable=True)
    event_id: Mapped[str] = mapped_column(String(100))
    transaction_id: Mapped[str] = mapped_column(String(100), default="")
    state: Mapped[str] = mapped_column(String(20))
    attempt: Mapped[int] = mapped_column(default=1)
    error_code: Mapped[str] = mapped_column(String(80), default="")
    error_message: Mapped[str] = mapped_column(String(500), default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("uq_pos_sync_event", "organization_id", "event_id", unique=True),)


class POSCustomer(Base):
    __tablename__ = "pos_customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_ref: Mapped[str] = mapped_column(String(100))
    full_name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(254), default="")
    membership_number: Mapped[str] = mapped_column(String(40))
    tier: Mapped[str] = mapped_column(String(24), default="standard")
    points_balance: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        Index("uq_pos_customer_ref", "organization_id", "customer_ref", unique=True),
        Index("uq_pos_membership", "organization_id", "membership_number", unique=True),
    )


class POSLoyaltyEntry(Base):
    __tablename__ = "pos_loyalty_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("pos_customers.id"), index=True)
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("pos_sales.id"), nullable=True)
    entry_key: Mapped[str] = mapped_column(String(100))
    points_delta: Mapped[int] = mapped_column()
    entry_type: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("uq_pos_loyalty_entry_key", "organization_id", "entry_key", unique=True),)


class DeviceRegisterIn(BaseModel):
    branch_id: str = Field(min_length=1, max_length=36)
    device_key: str = Field(min_length=16, max_length=100)
    name: str = Field(min_length=2, max_length=120)
    platform: str = Field(default="browser", max_length=80)


class DeviceSessionIn(BaseModel):
    device_secret: str = Field(min_length=32, max_length=128)


class DeviceDecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")


class ConflictIn(BaseModel):
    branch_id: str = Field(min_length=1, max_length=36)
    device_id: int | None = Field(default=None, ge=1)
    client_transaction_id: str = Field(min_length=8, max_length=100)
    conflict_type: str = Field(pattern="^(stale_stock|price_changed|shift_closed|duplicate|payload_mismatch|unknown)$")
    client_snapshot: dict[str, Any] = Field(default_factory=dict)
    server_snapshot: dict[str, Any] = Field(default_factory=dict)


class ConflictResolveIn(BaseModel):
    resolution: str = Field(pattern="^(accept_server|accept_client|void|retry_after_refresh)$")
    note: str = Field(min_length=5, max_length=500)


class SyncEventIn(BaseModel):
    branch_id: str = Field(min_length=1, max_length=36)
    device_id: int | None = Field(default=None, ge=1)
    event_id: str = Field(min_length=8, max_length=100)
    transaction_id: str = Field(default="", max_length=100)
    state: str = Field(pattern="^(queued|attempting|synced|retrying|dead_letter|conflict)$")
    attempt: int = Field(default=1, ge=1, le=1000)
    error_code: str = Field(default="", max_length=80)
    error_message: str = Field(default="", max_length=500)


class CustomerIn(BaseModel):
    customer_ref: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=2, max_length=160)
    phone: str = Field(default="", max_length=32)
    email: str = Field(default="", max_length=254)


class LoyaltyAwardIn(BaseModel):
    sale_id: int = Field(ge=1)
    entry_key: str = Field(min_length=8, max_length=100)
    points: int = Field(gt=0, le=1000000)
    note: str = Field(default="Purchase reward", max_length=300)


class LoyaltyRedeemIn(BaseModel):
    entry_key: str = Field(min_length=8, max_length=100)
    points: int = Field(gt=0, le=1000000)
    note: str = Field(min_length=3, max_length=300)


def _branch(membership, db, branch_id):
    from app.api.routes import _crm_branch_check
    _crm_branch_check(db, membership, branch_id)


@router.post("/devices/register", status_code=201)
def register_device(payload: DeviceRegisterIn, membership=Depends(active_membership),
                    user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "create")
    _branch(membership, db, payload.branch_id)
    row = db.query(POSDevice).filter_by(organization_id=membership.organization_id,
                                        device_key=payload.device_key).first()
    secret = secrets.token_urlsafe(40)
    if row:
        if row.status == "revoked":
            raise HTTPException(409, "Revoked device identity cannot be re-enrolled; generate a new device key")
        raise HTTPException(409, "Device is already registered")
    row = POSDevice(organization_id=membership.organization_id, branch_id=payload.branch_id,
        device_key=payload.device_key, name=payload.name.strip(), platform=payload.platform.strip(),
        token_digest=token_hash(secret), status="pending", registered_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "pos.device.registered", "pos_device", row.id)
    return {"id": row.id, "status": row.status, "device_secret": secret,
            "secret_displayed_once": True, "message": "Supervisor approval is required before use."}


@router.get("/devices")
def list_devices(membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    q = db.query(POSDevice).filter_by(organization_id=membership.organization_id)
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        q = q.filter(POSDevice.branch_id.in_(allowed)) if allowed else q.filter(POSDevice.id == -1)
    return [{"id":x.id,"branch_id":x.branch_id,"name":x.name,"platform":x.platform,
        "status":x.status,"last_seen_at":x.last_seen_at.isoformat() if x.last_seen_at else None}
        for x in q.order_by(POSDevice.id.desc()).limit(500).all()]


@router.post("/devices/{device_id}/decision")
def decide_device(device_id: int, payload: DeviceDecisionIn, membership=Depends(active_membership),
                  user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(POSDevice).filter_by(id=device_id, organization_id=membership.organization_id).with_for_update().first()
    if not row or not can_access_branch(membership, row.branch_id):
        raise HTTPException(404, "Device not found")
    if row.status != "pending":
        raise HTTPException(409, "Only pending devices can be approved or rejected")
    row.status = "trusted" if payload.decision == "approve" else "rejected"
    row.approved_by = user.id
    row.approved_at = utcnow()
    db.commit()
    audit(db, user.id, membership.organization_id, "pos.device."+row.status, "pos_device", row.id)
    return {"id":row.id,"status":row.status}


@router.post("/devices/{device_id}/revoke")
def revoke_device(device_id: int, membership=Depends(active_membership),
                  user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(POSDevice).filter_by(id=device_id, organization_id=membership.organization_id).with_for_update().first()
    if not row or not can_access_branch(membership, row.branch_id):
        raise HTTPException(404, "Device not found")
    row.status="revoked"; row.revoked_at=utcnow(); row.token_digest=secrets.token_hex(32)
    db.commit()
    audit(db, user.id, membership.organization_id, "pos.device.revoked", "pos_device", row.id)
    return {"id":row.id,"status":row.status,"sessions_revoked":True}


@router.post("/devices/{device_id}/session")
def validate_device_session(device_id: int, payload: DeviceSessionIn,
    membership=Depends(active_membership), user: User=Depends(current_user), db: Session=Depends(get_db)):
    row = db.query(POSDevice).filter_by(id=device_id, organization_id=membership.organization_id).first()
    if not row or not can_access_branch(membership, row.branch_id) or row.status != "trusted":
        raise HTTPException(403, "Trusted device approval is required")
    if not secrets.compare_digest(row.token_digest, token_hash(payload.device_secret)):
        raise HTTPException(401, "Invalid device credential")
    row.last_seen_at=utcnow(); db.commit()
    return {"device_id":row.id,"cashier_user_id":user.id,"branch_id":row.branch_id,
            "status":"active","checked_at":utcnow().isoformat(),
            "note":"This check confirms device trust; cashier API access still requires a valid user session."}


@router.post("/conflicts", status_code=201)
def create_conflict(payload: ConflictIn, membership=Depends(active_membership),
                    user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "create")
    _branch(membership, db, payload.branch_id)
    existing=db.query(POSSyncConflict).filter_by(organization_id=membership.organization_id,
        client_transaction_id=payload.client_transaction_id).first()
    if existing:
        return {"id":existing.id,"status":existing.status,"already_recorded":True}
    if payload.device_id:
        device=db.query(POSDevice).filter_by(id=payload.device_id,
            organization_id=membership.organization_id,branch_id=payload.branch_id,status="trusted").first()
        if not device: raise HTTPException(403,"Conflict device is not trusted")
    row=POSSyncConflict(organization_id=membership.organization_id,branch_id=payload.branch_id,
        device_id=payload.device_id,client_transaction_id=payload.client_transaction_id,
        conflict_type=payload.conflict_type,client_snapshot=payload.client_snapshot,
        server_snapshot=payload.server_snapshot,created_by=user.id)
    db.add(row); db.commit(); db.refresh(row)
    audit(db,user.id,membership.organization_id,"pos.sync_conflict.created","pos_sync_conflict",row.id)
    return {"id":row.id,"status":row.status}


@router.get("/conflicts")
def list_conflicts(status: str=Query(default="open", pattern="^(open|resolved|all)$"),
                   membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership,"read")
    q=db.query(POSSyncConflict).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None: q=q.filter(POSSyncConflict.branch_id.in_(allowed)) if allowed else q.filter(POSSyncConflict.id==-1)
    if status!="all": q=q.filter_by(status=status)
    return [{"id":x.id,"branch_id":x.branch_id,"device_id":x.device_id,
        "client_transaction_id":x.client_transaction_id,"conflict_type":x.conflict_type,
        "client_snapshot":x.client_snapshot,"server_snapshot":x.server_snapshot,
        "status":x.status,"created_at":x.created_at.isoformat()} for x in q.order_by(POSSyncConflict.id).limit(500).all()]


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(conflict_id:int,payload:ConflictResolveIn,membership=Depends(active_membership),
                     user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(POSSyncConflict).filter_by(id=conflict_id,organization_id=membership.organization_id).with_for_update().first()
    if not row or not can_access_branch(membership,row.branch_id): raise HTTPException(404,"Conflict not found")
    if row.status!="open": raise HTTPException(409,"Conflict has already been resolved")
    if payload.resolution=="accept_client":
        raise HTTPException(422,"Client payload cannot be accepted directly; retry through normal server validation")
    row.status="resolved"; row.resolution=payload.resolution; row.resolution_note=payload.note.strip()
    row.resolved_by=user.id; row.resolved_at=utcnow(); db.commit()
    audit(db,user.id,membership.organization_id,"pos.sync_conflict.resolved","pos_sync_conflict",row.id,payload.resolution)
    return {"id":row.id,"status":row.status,"resolution":row.resolution}


@router.get("/conflicts/by-transaction/{client_transaction_id}")
def conflict_resolution_status(client_transaction_id:str,membership=Depends(active_membership),
                               db:Session=Depends(get_db)):
    require_permission(membership,"read")
    row=db.query(POSSyncConflict).filter_by(
        organization_id=membership.organization_id,
        client_transaction_id=client_transaction_id
    ).first()
    if not row:
        return {"exists":False,"status":"none"}
    if not can_access_branch(membership,row.branch_id):
        raise HTTPException(404,"Conflict not found")
    return {"exists":True,"id":row.id,"status":row.status,"resolution":row.resolution,
            "resolution_note":row.resolution_note}


@router.post("/sync-events", status_code=201)
def record_sync_event(payload:SyncEventIn,membership=Depends(active_membership),
                      user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create"); _branch(membership,db,payload.branch_id)
    if payload.device_id:
        device=db.query(POSDevice).filter_by(id=payload.device_id,organization_id=membership.organization_id,
            branch_id=payload.branch_id,status="trusted").first()
        if not device: raise HTTPException(403,"Sync event device is not trusted")
    old=db.query(POSSyncEvent).filter_by(organization_id=membership.organization_id,event_id=payload.event_id).first()
    if old:
        if old.transaction_id!=payload.transaction_id or old.state!=payload.state:
            raise HTTPException(409,"Sync event ID reused with different event data")
        return {"id":old.id,"status":"already_recorded"}
    row=POSSyncEvent(organization_id=membership.organization_id,branch_id=payload.branch_id,
        device_id=payload.device_id,event_id=payload.event_id,transaction_id=payload.transaction_id,
        state=payload.state,attempt=payload.attempt,error_code=payload.error_code,
        error_message=payload.error_message,occurred_at=utcnow())
    db.add(row); db.commit(); db.refresh(row)
    return {"id":row.id,"status":"recorded"}


@router.get("/sync-dashboard")
def sync_dashboard(membership=Depends(active_membership), db:Session=Depends(get_db)):
    require_permission(membership,"read")
    q=db.query(POSSyncEvent).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None: q=q.filter(POSSyncEvent.branch_id.in_(allowed)) if allowed else q.filter(POSSyncEvent.id==-1)
    rows=q.order_by(POSSyncEvent.occurred_at.desc()).limit(5000).all()
    counts={k:0 for k in ("queued","attempting","synced","retrying","dead_letter","conflict")}
    for row in rows: counts[row.state]=counts.get(row.state,0)+1
    return {"counts":counts,"events":[{"id":x.id,"branch_id":x.branch_id,"device_id":x.device_id,
        "transaction_id":x.transaction_id,"state":x.state,"attempt":x.attempt,
        "error_code":x.error_code,"error_message":x.error_message,
        "occurred_at":x.occurred_at.isoformat()} for x in rows[:200]],
        "last_event_at":rows[0].occurred_at.isoformat() if rows else None,
        "note":"Dashboard reflects client-reported sync telemetry; a background worker must submit events."}


@router.post("/customers", status_code=201)
def upsert_customer(payload:CustomerIn,membership=Depends(active_membership),
                    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(POSCustomer).filter_by(organization_id=membership.organization_id,
        customer_ref=payload.customer_ref).with_for_update().first()
    if row:
        row.full_name=payload.full_name.strip(); row.phone=payload.phone.strip(); row.email=payload.email.strip()
    else:
        row=POSCustomer(organization_id=membership.organization_id,customer_ref=payload.customer_ref,
            full_name=payload.full_name.strip(),phone=payload.phone.strip(),email=payload.email.strip(),
            membership_number="OC-"+secrets.token_hex(6).upper())
        db.add(row)
    db.commit(); db.refresh(row)
    audit(db,user.id,membership.organization_id,"pos.customer.updated","pos_customer",row.id)
    return {"id":row.id,"customer_ref":row.customer_ref,"membership_number":row.membership_number,
            "tier":row.tier,"points_balance":row.points_balance}


@router.get("/customers")
def list_customers(membership=Depends(active_membership),db:Session=Depends(get_db),
                   limit:int=Query(default=100,ge=1,le=500)):
    require_permission(membership,"read")
    rows=db.query(POSCustomer).filter_by(organization_id=membership.organization_id,is_active=True).order_by(POSCustomer.id.desc()).limit(limit).all()
    return [{"id":x.id,"customer_ref":x.customer_ref,"full_name":x.full_name,"phone":x.phone,
        "membership_number":x.membership_number,"tier":x.tier,"points_balance":x.points_balance} for x in rows]


@router.post("/customers/{customer_id}/loyalty/award")
def award_points(customer_id:int,payload:LoyaltyAwardIn,membership=Depends(active_membership),
                 user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    customer=db.query(POSCustomer).filter_by(id=customer_id,organization_id=membership.organization_id,is_active=True).with_for_update().first()
    sale=db.query(POSSale).filter_by(id=payload.sale_id,organization_id=membership.organization_id).first()
    if not customer or not sale: raise HTTPException(404,"Customer or sale not found")
    if not can_access_branch(membership,sale.branch_id): raise HTTPException(404,"Sale not found")
    old=db.query(POSLoyaltyEntry).filter_by(organization_id=membership.organization_id,entry_key=payload.entry_key).first()
    if old:
        if old.customer_id!=customer.id or old.sale_id!=sale.id or old.points_delta!=payload.points:
            raise HTTPException(409,"Loyalty idempotency key conflict")
        return {"id":old.id,"points_balance":customer.points_balance,"already_recorded":True}
    row=POSLoyaltyEntry(organization_id=membership.organization_id,customer_id=customer.id,sale_id=sale.id,
        entry_key=payload.entry_key,points_delta=payload.points,entry_type="earn",
        note=payload.note.strip(),created_by=user.id)
    customer.points_balance+=payload.points; db.add(row); db.commit(); db.refresh(row)
    audit(db,user.id,membership.organization_id,"pos.loyalty.awarded","pos_customer",customer.id,str(payload.points))
    return {"id":row.id,"points_awarded":payload.points,"points_balance":customer.points_balance}


@router.post("/customers/{customer_id}/loyalty/redeem")
def redeem_points(customer_id:int,payload:LoyaltyRedeemIn,membership=Depends(active_membership),
                  user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    customer=db.query(POSCustomer).filter_by(id=customer_id,organization_id=membership.organization_id,is_active=True).with_for_update().first()
    if not customer: raise HTTPException(404,"Customer not found")
    old=db.query(POSLoyaltyEntry).filter_by(organization_id=membership.organization_id,entry_key=payload.entry_key).first()
    if old:
        if old.customer_id!=customer.id or old.points_delta!=-payload.points: raise HTTPException(409,"Loyalty idempotency key conflict")
        return {"id":old.id,"points_balance":customer.points_balance,"already_recorded":True}
    if customer.points_balance<payload.points: raise HTTPException(422,"Insufficient loyalty points")
    row=POSLoyaltyEntry(organization_id=membership.organization_id,customer_id=customer.id,
        entry_key=payload.entry_key,points_delta=-payload.points,entry_type="redeem",
        note=payload.note.strip(),created_by=user.id)
    customer.points_balance-=payload.points; db.add(row); db.commit(); db.refresh(row)
    audit(db,user.id,membership.organization_id,"pos.loyalty.redeemed","pos_customer",customer.id,str(payload.points))
    return {"id":row.id,"points_redeemed":payload.points,"points_balance":customer.points_balance}


@router.get("/customers/{customer_id}/history")
def customer_history(customer_id:int,membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    customer=db.query(POSCustomer).filter_by(id=customer_id,organization_id=membership.organization_id).first()
    if not customer: raise HTTPException(404,"Customer not found")
    entries=db.query(POSLoyaltyEntry).filter_by(organization_id=membership.organization_id,customer_id=customer.id).order_by(POSLoyaltyEntry.created_at.desc()).limit(500).all()
    purchases=db.query(POSSale).filter_by(organization_id=membership.organization_id,customer_id=customer.id).order_by(POSSale.created_at.desc()).limit(500).all()
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        purchases=[sale for sale in purchases if sale.branch_id in allowed]
    return {"customer":{"id":customer.id,"full_name":customer.full_name,"membership_number":customer.membership_number,
        "tier":customer.tier,"points_balance":customer.points_balance},
        "loyalty_history":[{"id":x.id,"sale_id":x.sale_id,"entry_type":x.entry_type,
            "points_delta":x.points_delta,"note":x.note,"created_at":x.created_at.isoformat()} for x in entries],
        "purchase_history":[{"sale_id":sale.id,"branch_id":sale.branch_id,"status":sale.status,
            "total_amount":str(sale.total_amount),"currency":sale.currency,
            "created_at":sale.created_at.isoformat()} for sale in purchases]}


@router.get("/operations-report")
def operations_report(membership=Depends(active_membership),db:Session=Depends(get_db),
                      limit:int=Query(default=90,ge=1,le=365)):
    require_permission(membership,"read")
    q=db.query(POSSale).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None: q=q.filter(POSSale.branch_id.in_(allowed)) if allowed else q.filter(POSSale.id==-1)
    rows=q.order_by(POSSale.created_at.desc()).limit(limit*1000).all()
    branches={}
    for sale in rows:
        b=branches.setdefault(sale.branch_id,{"sales_count":0,"gross_total":Decimal("0.00"),"shifts":set()})
        b["sales_count"]+=1; b["gross_total"]+=Decimal(str(sale.total_amount)); b["shifts"].add(sale.shift_id)
    return {"branches":[{"branch_id":k,"sales_count":v["sales_count"],"gross_total":str(v["gross_total"]),
        "shift_count":len(v["shifts"])} for k,v in sorted(branches.items())],
        "total_sales":sum(v["sales_count"] for v in branches.values()),
        "gross_total":str(sum((v["gross_total"] for v in branches.values()),Decimal("0.00"))),
        "note":"Branch report is based on posted POS sale headers; it excludes unsettled external payment settlement and physical till-device telemetry."}
