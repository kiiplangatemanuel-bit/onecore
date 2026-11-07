import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import AuditEvent, Branch, POSShift, POSSale, POSPayment, POSRefund
from app.core.pos_completion_models import POSDevice, POSOfflineConflict, POSCustomer, POSLoyaltyEntry, POSPeripheralCommand, POSCustomerSale
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, can_access_branch, branch_scope_ids

router = APIRouter(prefix="/api/v1/pos", tags=["POS completion"])
def _audit(db, user, org, action, kind, ident, detail=""):
    db.add(AuditEvent(actor_user_id=user.id, organization_id=org, action=action, resource_type=kind, resource_id=str(ident), detail=detail))
def _branch(membership, branch_id):
    if not can_access_branch(membership, branch_id):
        raise HTTPException(403, "Branch access denied")
def _tenant_branch(db, membership, branch_id):
    _branch(membership, branch_id)
    if not db.query(Branch).filter_by(id=branch_id,organization_id=membership.organization_id,is_active=True).first():
        raise HTTPException(404,"Branch not found in this organization")
def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()
def _device(db, membership, device_id, token, branch_id=None):
    q=db.query(POSDevice).filter_by(id=device_id, organization_id=membership.organization_id)
    if branch_id: q=q.filter_by(branch_id=branch_id)
    row=q.first()
    if not row or row.status!="active" or not secrets.compare_digest(row.credential_hash,_hash(token or "")):
        raise HTTPException(401,"Trusted POS device authentication failed")
    expires=row.offline_until
    if expires and expires.tzinfo is None: expires=expires.replace(tzinfo=timezone.utc)
    if expires and expires < datetime.now(timezone.utc):
        raise HTTPException(401,"Device offline authorization expired; reconnect and re-authorize")
    _branch(membership,row.branch_id)
    row.last_seen_at=datetime.now(timezone.utc)
    return row

class DeviceIn(BaseModel):
    device_key: str = Field(min_length=8,max_length=100,pattern=r"^[A-Za-z0-9._:-]+$")
    branch_id: str = Field(min_length=1,max_length=36)
    name: str = Field(min_length=2,max_length=120)
    platform: str = Field(default="browser",pattern=r"^(browser|android|ios|windows|linux|macos)$")
class ConflictIn(BaseModel):
    shift_id: int = Field(gt=0)
    client_transaction_id: str = Field(min_length=8,max_length=100)
    conflict_type: str = Field(pattern=r"^(stale_stock|shift_closed|price_changed|duplicate_transaction|device_revoked|offline_expired|unknown_product)$")
    server_snapshot: dict = Field(default_factory=dict)
    client_snapshot: dict = Field(default_factory=dict)
class ResolveIn(BaseModel):
    decision: str = Field(pattern=r"^(accept_server|discard_local)$")
    note: str = Field(min_length=3,max_length=500)
class CustomerIn(BaseModel):
    full_name: str = Field(min_length=2,max_length=180)
    phone: str = Field(default="",max_length=32)
    email: str = Field(default="",max_length=320)
    branch_id: str | None = Field(default=None,max_length=36)
class CustomerSaleIn(BaseModel):
    sale_id: int = Field(gt=0)
class LoyaltyRedeemIn(BaseModel):
    points: int = Field(gt=0,le=1000000)
    idempotency_key: str = Field(min_length=8,max_length=100)
    note: str = Field(default="Reward redemption",min_length=3,max_length=300)
class PeripheralIn(BaseModel):
    device_id: int = Field(gt=0)
    sale_id: int | None = Field(default=None,gt=0)
    peripheral_type: str = Field(pattern=r"^(receipt_printer|cash_drawer)$")
    command: str = Field(pattern=r"^(print_receipt|open_drawer|test_print)$")
    payload: dict = Field(default_factory=dict)
class PeripheralAckIn(BaseModel):
    status: str = Field(pattern=r"^(completed|failed)$")
    result: dict = Field(default_factory=dict)
class SettlementIn(BaseModel):
    provider_reference: str = Field(min_length=3,max_length=120)
    evidence_note: str = Field(min_length=5,max_length=500)

@router.post("/devices/register",status_code=201)
def register_device(payload:DeviceIn,membership=Depends(active_membership),user=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage"); _tenant_branch(db,membership,payload.branch_id)
    if not db.query(POSDevice).filter_by(organization_id=membership.organization_id,device_key=payload.device_key).first():
        pass
    else: raise HTTPException(409,"Device key already registered; use device re-enrolment after revocation")
    token=secrets.token_urlsafe(40)
    row=POSDevice(organization_id=membership.organization_id,branch_id=payload.branch_id,device_key=payload.device_key,
        name=payload.name,platform=payload.platform,credential_hash=_hash(token),status="pending",created_by=user.id)
    db.add(row); db.flush(); _audit(db,user,membership.organization_id,"pos.device.registered","pos_device",row.id)
    db.commit()
    return {"id":row.id,"status":row.status,"device_token":token,"token_warning":"Store this token in secure device storage. It is shown once."}

@router.post("/devices/{device_id}/approve")
def approve_device(device_id:int,membership=Depends(active_membership),user=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(POSDevice).filter_by(id=device_id,organization_id=membership.organization_id).with_for_update().first()
    if not row: raise HTTPException(404,"Device not found")
    _branch(membership,row.branch_id)
    if row.status=="revoked": raise HTTPException(409,"Revoked device cannot be reactivated; register a new device identity")
    row.status="active"; row.offline_until=datetime.now(timezone.utc)+timedelta(hours=24)
    _audit(db,user,membership.organization_id,"pos.device.approved","pos_device",row.id); db.commit()
    return {"id":row.id,"status":row.status,"offline_until":row.offline_until}

@router.post("/devices/{device_id}/renew-offline")
def renew_device(device_id:int,membership=Depends(active_membership),user=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(POSDevice).filter_by(id=device_id,organization_id=membership.organization_id,status="active").first()
    if not row: raise HTTPException(404,"Active device not found")
    _branch(membership,row.branch_id); row.offline_until=datetime.now(timezone.utc)+timedelta(hours=24)
    _audit(db,user,membership.organization_id,"pos.device.offline_renewed","pos_device",row.id); db.commit()
    return {"id":row.id,"offline_until":row.offline_until}

@router.post("/devices/{device_id}/revoke")
def revoke_device(device_id:int,membership=Depends(active_membership),user=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(POSDevice).filter_by(id=device_id,organization_id=membership.organization_id).with_for_update().first()
    if not row: raise HTTPException(404,"Device not found")
    _branch(membership,row.branch_id); row.status="revoked"; row.revoked_by=user.id; row.revoked_at=datetime.now(timezone.utc); row.offline_until=datetime.now(timezone.utc)
    _audit(db,user,membership.organization_id,"pos.device.revoked","pos_device",row.id); db.commit()
    return {"id":row.id,"status":row.status,"revoked_at":row.revoked_at}

@router.get("/devices")
def list_devices(membership=Depends(active_membership),db:Session=Depends(get_db)):
    q=db.query(POSDevice).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:q=q.filter(POSDevice.branch_id.in_(allowed or ["__none__"]))
    return [{"id":x.id,"branch_id":x.branch_id,"device_key":x.device_key,"name":x.name,"platform":x.platform,"status":x.status,
        "offline_until":x.offline_until,"last_seen_at":x.last_seen_at,"last_sync_at":x.last_sync_at,
        "last_sync_status":x.last_sync_status,"last_sync_error":x.last_sync_error} for x in q.order_by(POSDevice.id.desc()).limit(500)]

@router.post("/devices/{device_id}/conflicts",status_code=201)
def report_conflict(device_id:int,payload:ConflictIn,x_pos_device_token:str=Header(default=""),membership=Depends(active_membership),db:Session=Depends(get_db)):
    device=_device(db,membership,device_id,x_pos_device_token)
    shift=db.query(POSShift).filter_by(id=payload.shift_id,organization_id=membership.organization_id,branch_id=device.branch_id).first()
    if not shift: raise HTTPException(404,"Shift not found for trusted device branch")
    existing=db.query(POSOfflineConflict).filter_by(organization_id=membership.organization_id,device_id=device.id,client_transaction_id=payload.client_transaction_id).first()
    if existing:
        if existing.conflict_type!=payload.conflict_type: raise HTTPException(409,"Conflict key already used with different conflict data")
        return {"id":existing.id,"status":existing.status,"idempotent":True}
    row=POSOfflineConflict(organization_id=membership.organization_id,branch_id=device.branch_id,device_id=device.id,shift_id=shift.id,
        client_transaction_id=payload.client_transaction_id,conflict_type=payload.conflict_type,
        server_snapshot=payload.server_snapshot,client_snapshot=payload.client_snapshot)
    db.add(row); device.last_sync_status="conflict"; device.last_sync_error=payload.conflict_type
    db.flush(); db.commit()
    return {"id":row.id,"status":row.status,"resolution_required":True}

@router.get("/conflicts")
def list_conflicts(status:str=Query(default="pending",pattern="^(pending|resolved|all)$"),membership=Depends(active_membership),db:Session=Depends(get_db)):
    q=db.query(POSOfflineConflict).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:q=q.filter(POSOfflineConflict.branch_id.in_(allowed or ["__none__"]))
    if status!="all":q=q.filter_by(status=status)
    return [{"id":x.id,"branch_id":x.branch_id,"device_id":x.device_id,"shift_id":x.shift_id,"client_transaction_id":x.client_transaction_id,
        "conflict_type":x.conflict_type,"server_snapshot":x.server_snapshot,"client_snapshot":x.client_snapshot,"status":x.status,
        "resolution":x.resolution,"resolution_note":x.resolution_note,"created_at":x.created_at} for x in q.order_by(POSOfflineConflict.id.desc()).limit(500)]

@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(conflict_id:int,payload:ResolveIn,membership=Depends(active_membership),user=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(POSOfflineConflict).filter_by(id=conflict_id,organization_id=membership.organization_id).with_for_update().first()
    if not row: raise HTTPException(404,"Conflict not found")
    _branch(membership,row.branch_id)
    if row.status!="pending": raise HTTPException(409,"Conflict has already been resolved")
    row.status="resolved"; row.resolution=payload.decision; row.resolution_note=payload.note.strip(); row.resolved_by=user.id; row.resolved_at=datetime.now(timezone.utc)
    _audit(db,user,membership.organization_id,"pos.offline_conflict.resolved","pos_offline_conflict",row.id,payload.decision)
    db.commit()
    return {"id":row.id,"status":row.status,"resolution":row.resolution,"safe_to_retry":False,
        "instruction":"Resolution records the supervisor decision only. Never replay a queued payment automatically; reconcile tender status and create a new sale only after confirming no payment was captured."}

@router.post("/devices/{device_id}/sync-heartbeat")
def sync_heartbeat(device_id:int,x_pos_device_token:str=Header(default=""),status:str=Query(default="success",pattern="^(success|partial|failed|conflict)$"),
                   error:str=Query(default="",max_length=500),membership=Depends(active_membership),db:Session=Depends(get_db)):
    device=_device(db,membership,device_id,x_pos_device_token); now=datetime.now(timezone.utc)
    device.last_sync_at=now; device.last_sync_status=status; device.last_sync_error=error
    db.commit(); return {"device_id":device.id,"last_sync_at":now,"status":status}

@router.get("/sync/monitor")
def sync_monitor(membership=Depends(active_membership),db:Session=Depends(get_db)):
    q=db.query(POSDevice).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:q=q.filter(POSDevice.branch_id.in_(allowed or ["__none__"]))
    rows=q.all(); now=datetime.now(timezone.utc)
    return {"devices":len(rows),"active":sum(x.status=="active" for x in rows),
        "never_synced":sum(x.last_sync_at is None for x in rows),
        "stale":sum(x.status=="active" and (x.last_sync_at is None or x.last_sync_at<now-timedelta(hours=1)) for x in rows),
        "failed":sum(x.last_sync_status in {"failed","partial","conflict"} for x in rows),
        "pending_conflicts":db.query(func.count(POSOfflineConflict.id)).filter(
            POSOfflineConflict.organization_id==membership.organization_id,POSOfflineConflict.status=="pending",
            POSOfflineConflict.branch_id.in_(allowed or ["__none__"]) if allowed is not None else True).scalar() or 0,
        "items":[{"device_id":x.id,"device":x.name,"branch_id":x.branch_id,"status":x.status,"last_sync_at":x.last_sync_at,
            "sync_status":x.last_sync_status,"error":x.last_sync_error} for x in rows]}

@router.post("/customers",status_code=201)
def create_customer(payload:CustomerIn,membership=Depends(active_membership),user=Depends(current_user),db:Session=Depends(get_db)):
    if payload.branch_id:_tenant_branch(db,membership,payload.branch_id)
    if payload.phone and db.query(POSCustomer).filter_by(organization_id=membership.organization_id,phone=payload.phone).first():
        raise HTTPException(409,"Customer phone already exists in this organization")
    row=POSCustomer(organization_id=membership.organization_id,branch_id=payload.branch_id,customer_number="C"+secrets.token_hex(6).upper(),
        full_name=payload.full_name.strip(),phone=payload.phone.strip(),email=payload.email.strip().lower())
    db.add(row); db.flush(); _audit(db,user,membership.organization_id,"pos.customer.created","pos_customer",row.id); db.commit()
    return {"id":row.id,"customer_number":row.customer_number,"full_name":row.full_name,"phone":row.phone,"points_balance":row.points_balance}

@router.get("/customers")
def search_customers(q:str=Query(default="",max_length=120),membership=Depends(active_membership),db:Session=Depends(get_db)):
    query=db.query(POSCustomer).filter_by(organization_id=membership.organization_id,is_active=True)
    allowed=branch_scope_ids(membership)
    if allowed is not None:query=query.filter((POSCustomer.branch_id.is_(None))|(POSCustomer.branch_id.in_(allowed or ["__none__"])))
    if q:query=query.filter((POSCustomer.full_name.ilike(f"%{q}%"))|(POSCustomer.phone.ilike(f"%{q}%"))|(POSCustomer.customer_number.ilike(f"%{q}%")))
    return [{"id":x.id,"customer_number":x.customer_number,"full_name":x.full_name,"phone":x.phone,"email":x.email,
        "membership_tier":x.membership_tier,"points_balance":x.points_balance,"lifetime_spend":str(x.lifetime_spend)} for x in query.order_by(POSCustomer.full_name).limit(100)]

@router.post("/customers/{customer_id}/sales")
def link_customer_sale(customer_id:int,payload:CustomerSaleIn,membership=Depends(active_membership),user=Depends(current_user),db:Session=Depends(get_db)):
    customer=db.query(POSCustomer).filter_by(id=customer_id,organization_id=membership.organization_id,is_active=True).with_for_update().first()
    sale=db.query(POSSale).filter_by(id=payload.sale_id,organization_id=membership.organization_id,status="posted").first()
    if not customer or not sale:raise HTTPException(404,"Customer or posted sale not found")
    _branch(membership,sale.branch_id)
    if db.query(POSCustomerSale).filter_by(organization_id=membership.organization_id,sale_id=sale.id).first():raise HTTPException(409,"Sale already linked to a customer")
    db.add(POSCustomerSale(organization_id=membership.organization_id,customer_id=customer.id,sale_id=sale.id))
    customer.lifetime_spend=Decimal(customer.lifetime_spend or 0)+Decimal(sale.total_amount)
    earn=int(Decimal(sale.total_amount)//Decimal("100"))
    if earn:
        key=f"sale:{sale.id}:earn"
        if not db.query(POSLoyaltyEntry).filter_by(organization_id=membership.organization_id,idempotency_key=key).first():
            db.add(POSLoyaltyEntry(organization_id=membership.organization_id,customer_id=customer.id,sale_id=sale.id,entry_type="earn",
                points_delta=earn,idempotency_key=key,note="1 point per 100 currency units spent",created_by=user.id))
            customer.points_balance+=earn
    _audit(db,user,membership.organization_id,"pos.customer.sale_linked","pos_sale",sale.id); db.commit()
    return {"customer_id":customer.id,"sale_id":sale.id,"points_earned":earn,"points_balance":customer.points_balance}

@router.get("/customers/{customer_id}/history")
def customer_history(customer_id:int,membership=Depends(active_membership),db:Session=Depends(get_db)):
    customer=db.query(POSCustomer).filter_by(id=customer_id,organization_id=membership.organization_id).first()
    if not customer:raise HTTPException(404,"Customer not found")
    allowed=branch_scope_ids(membership)
    if customer.branch_id:_branch(membership,customer.branch_id)
    query=db.query(POSSale).join(POSCustomerSale,POSCustomerSale.sale_id==POSSale.id).filter(
        POSCustomerSale.customer_id==customer.id,POSSale.organization_id==membership.organization_id)
    if allowed is not None:query=query.filter(POSSale.branch_id.in_(allowed or ["__none__"]))
    rows=query.order_by(POSSale.created_at.desc()).limit(200).all()
    return {"customer":{"id":customer.id,"name":customer.full_name,"tier":customer.membership_tier,"points_balance":customer.points_balance,
        "lifetime_spend":str(customer.lifetime_spend)},"purchases":[{"sale_id":x.id,"branch_id":x.branch_id,"total":str(x.total_amount),"currency":x.currency,"created_at":x.created_at} for x in rows]}

@router.post("/customers/{customer_id}/rewards/redeem")
def redeem_points(customer_id:int,payload:LoyaltyRedeemIn,membership=Depends(active_membership),user=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    customer=db.query(POSCustomer).filter_by(id=customer_id,organization_id=membership.organization_id,is_active=True).with_for_update().first()
    if not customer:raise HTTPException(404,"Customer not found")
    existing=db.query(POSLoyaltyEntry).filter_by(organization_id=membership.organization_id,idempotency_key=payload.idempotency_key).first()
    if existing:
        if existing.customer_id!=customer.id or existing.points_delta!=-payload.points:raise HTTPException(409,"Idempotency key reused with different redemption")
        return {"id":existing.id,"points_balance":customer.points_balance,"idempotent":True}
    if customer.branch_id:_branch(membership,customer.branch_id)
    if customer.points_balance<payload.points:raise HTTPException(422,"Insufficient loyalty points")
    customer.points_balance-=payload.points
    row=POSLoyaltyEntry(organization_id=membership.organization_id,customer_id=customer.id,entry_type="redeem",
        points_delta=-payload.points,idempotency_key=payload.idempotency_key,note=payload.note,created_by=user.id)
    db.add(row); _audit(db,user,membership.organization_id,"pos.loyalty.redeemed","pos_customer",customer.id,str(payload.points)); db.commit()
    return {"id":row.id,"points_redeemed":payload.points,"points_balance":customer.points_balance}

@router.post("/peripherals/commands",status_code=201)
def queue_peripheral(payload:PeripheralIn,membership=Depends(active_membership),user=Depends(current_user),db:Session=Depends(get_db)):
    device=db.query(POSDevice).filter_by(id=payload.device_id,organization_id=membership.organization_id,status="active").first()
    if not device:raise HTTPException(404,"Active POS device not found")
    _branch(membership,device.branch_id)
    if payload.peripheral_type=="receipt_printer" and payload.command=="open_drawer":raise HTTPException(422,"Cash drawer command requires cash_drawer peripheral")
    if payload.peripheral_type=="cash_drawer" and payload.command=="print_receipt":raise HTTPException(422,"Receipt printing requires receipt_printer peripheral")
    sale=None
    if payload.sale_id:
        sale=db.query(POSSale).filter_by(id=payload.sale_id,organization_id=membership.organization_id,status="posted").first()
        if not sale or sale.branch_id!=device.branch_id:raise HTTPException(404,"Sale not found for device branch")
    row=POSPeripheralCommand(organization_id=membership.organization_id,branch_id=device.branch_id,device_id=device.id,sale_id=payload.sale_id,
        peripheral_type=payload.peripheral_type,command=payload.command,payload=payload.payload,status="queued")
    db.add(row); db.flush(); _audit(db,user,membership.organization_id,"pos.peripheral.queued","pos_peripheral_command",row.id); db.commit()
    return {"id":row.id,"status":row.status,"delivery":"queued for trusted device agent; physical hardware is driven by the local device bridge"}

@router.get("/devices/{device_id}/peripherals/commands")
def poll_peripheral(device_id:int,x_pos_device_token:str=Header(default=""),membership=Depends(active_membership),db:Session=Depends(get_db)):
    device=_device(db,membership,device_id,x_pos_device_token)
    rows=db.query(POSPeripheralCommand).filter_by(organization_id=membership.organization_id,device_id=device.id,status="queued").order_by(POSPeripheralCommand.id).limit(25).all()
    for row in rows:row.status="delivered"
    db.commit()
    return [{"id":x.id,"peripheral_type":x.peripheral_type,"command":x.command,"payload":x.payload,"sale_id":x.sale_id} for x in rows]

@router.post("/devices/{device_id}/peripherals/commands/{command_id}/ack")
def acknowledge_peripheral(device_id:int,command_id:int,payload:PeripheralAckIn,x_pos_device_token:str=Header(default=""),membership=Depends(active_membership),db:Session=Depends(get_db)):
    device=_device(db,membership,device_id,x_pos_device_token)
    row=db.query(POSPeripheralCommand).filter_by(id=command_id,organization_id=membership.organization_id,device_id=device.id).with_for_update().first()
    if not row:raise HTTPException(404,"Peripheral command not found")
    if row.status in {"completed","failed"}:return {"id":row.id,"status":row.status,"idempotent":True}
    row.status=payload.status; row.result=payload.result; row.acknowledged_at=datetime.now(timezone.utc); db.commit()
    return {"id":row.id,"status":row.status}

@router.post("/payments/{payment_id}/verify-settlement")
def verify_settlement(payment_id:int,payload:SettlementIn,membership=Depends(active_membership),user=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    payment=db.query(POSPayment).filter_by(id=payment_id,organization_id=membership.organization_id).with_for_update().first()
    if not payment:raise HTTPException(404,"Payment not found")
    sale=db.query(POSSale).filter_by(id=payment.sale_id,organization_id=membership.organization_id).first()
    _branch(membership,sale.branch_id)
    if payment.method=="mpesa": raise HTTPException(409,"M-Pesa settlement must be verified by the Daraja callback flow")
    if payment.status=="recorded":
        if payment.provider_reference==payload.provider_reference:return {"payment_id":payment.id,"status":"recorded","idempotent":True}
        raise HTTPException(409,"Payment is already recorded against another reference")
    if payment.provider_reference and payment.provider_reference!=payload.provider_reference:raise HTTPException(409,"Provider reference does not match payment intent")
    payment.provider_reference=payload.provider_reference; payment.status="recorded"
    _audit(db,user,membership.organization_id,"pos.payment.settlement_verified","pos_payment",payment.id,payload.evidence_note.strip()); db.commit()
    return {"payment_id":payment.id,"status":payment.status,"note":"Manual supervisor verification recorded. Automated bank/provider settlement matching still requires a provider feed."}

@router.get("/operations/report")
def operations_report(branch_id:str|None=None,membership=Depends(active_membership),db:Session=Depends(get_db)):
    q=db.query(POSSale).filter_by(organization_id=membership.organization_id,status="posted")
    allowed=branch_scope_ids(membership)
    if branch_id:
        _branch(membership,branch_id); q=q.filter_by(branch_id=branch_id)
    elif allowed is not None:q=q.filter(POSSale.branch_id.in_(allowed or ["__none__"]))
    rows=q.all()
    shifts=db.query(POSShift).filter_by(organization_id=membership.organization_id)
    if branch_id:shifts=shifts.filter_by(branch_id=branch_id)
    elif allowed is not None:shifts=shifts.filter(POSShift.branch_id.in_(allowed or ["__none__"]))
    shift_rows=shifts.all()
    tender_query=db.query(func.count(POSPayment.id)).join(POSSale,POSPayment.sale_id==POSSale.id).filter(
        POSPayment.organization_id==membership.organization_id,POSPayment.status=="unsettled")
    if branch_id:tender_query=tender_query.filter(POSSale.branch_id==branch_id)
    elif allowed is not None:tender_query=tender_query.filter(POSSale.branch_id.in_(allowed or ["__none__"]))
    return {"sales_count":len(rows),"sales_total":str(sum((Decimal(x.total_amount) for x in rows),Decimal("0"))),
        "by_branch":[{"branch_id":b,"sales_count":sum(x.branch_id==b for x in rows),
        "sales_total":str(sum((Decimal(x.total_amount) for x in rows if x.branch_id==b),Decimal("0")))} for b in sorted({x.branch_id for x in rows})],
        "shifts":{"open":sum(x.status=="open" for x in shift_rows),"closed":sum(x.status!="open" for x in shift_rows),
        "pending_review":sum(x.reconciliation_status=="pending_review" for x in shift_rows)},
        "unsettled_tenders":tender_query.scalar() or 0}

@router.post("/refunds/{refund_id}/confirm-execution")
def confirm_refund_execution(refund_id:int,payload:SettlementIn,membership=Depends(active_membership),user=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    refund=db.query(POSRefund).filter_by(id=refund_id,organization_id=membership.organization_id).with_for_update().first()
    if not refund: raise HTTPException(404,"Refund not found")
    if refund.method=="mpesa": raise HTTPException(409,"M-Pesa refund execution must be confirmed by the Daraja B2C result callback")
    from app.core.models import POSReturn
    ret=db.query(POSReturn).filter_by(id=refund.return_id,organization_id=membership.organization_id).first()
    sale=db.query(POSSale).filter_by(id=ret.sale_id,organization_id=membership.organization_id).first() if ret else None
    if not sale: raise HTTPException(404,"Original sale not found")
    _branch(membership,sale.branch_id)
    if refund.status=="recorded":
        if refund.provider_reference==payload.provider_reference:return {"refund_id":refund.id,"status":"recorded","idempotent":True}
        raise HTTPException(409,"Refund already confirmed with another reference")
    refund.provider_reference=payload.provider_reference
    refund.status="recorded"
    _audit(db,user,membership.organization_id,"pos.refund.execution_confirmed","pos_refund",refund.id,payload.evidence_note.strip())
    db.commit()
    return {"refund_id":refund.id,"status":refund.status,"note":"Supervisor-confirmed physical/provider evidence recorded; no payment gateway is called by this endpoint."}

@router.post("/devices/{device_id}/bind-shift")
def bind_device_shift(device_id:int,shift_id:int=Query(gt=0),x_pos_device_token:str=Header(default=""),
                     membership=Depends(active_membership),user=Depends(current_user),db:Session=Depends(get_db)):
    device=_device(db,membership,device_id,x_pos_device_token)
    shift=db.query(POSShift).filter_by(id=shift_id,organization_id=membership.organization_id,branch_id=device.branch_id).with_for_update().first()
    if not shift:raise HTTPException(404,"Cashier shift not found for device branch")
    if shift.status!="open":raise HTTPException(409,"Only an open cashier shift can be bound to a device")
    if shift.cashier_user_id!=user.id:raise HTTPException(403,"Only the authenticated cashier who owns this shift can bind the device")
    if shift.device_id and shift.device_id!=device.id:raise HTTPException(409,"Shift is already bound to another device")
    other=db.query(POSShift).filter_by(organization_id=membership.organization_id,device_id=device.id,status="open").filter(POSShift.id!=shift.id).first()
    if other:raise HTTPException(409,"Trusted device already has another open shift")
    shift.device_id=device.id
    _audit(db,user,membership.organization_id,"pos.device.shift_bound","pos_shift",shift.id,f"device:{device.id}")
    db.commit()
    return {"device_id":device.id,"shift_id":shift.id,"cashier_user_id":shift.cashier_user_id,"status":"bound"}
