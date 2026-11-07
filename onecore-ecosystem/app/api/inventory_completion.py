"""Inventory completion APIs: warehouse logistics, reservations, batches, stocktakes, pricing and controls."""
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from pydantic import BaseModel, Field, model_validator
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import User, Branch, InventoryProduct, InventoryStockMovement, AuditEvent
from app.core.inventory_models import (InventoryWarehouse, InventoryTransfer, InventoryTransferLine,
    InventoryReservation, InventoryBatch, InventoryStocktake, InventoryStocktakeLine,
    InventoryReorderRule, InventoryPriceList, InventoryPrice)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, branch_scope_ids, can_access_branch

router = APIRouter(prefix="/api/v1/inventory", tags=["Inventory completion"])
Q3 = Decimal("0.001")
MONEY = Decimal("0.01")


def dec(value):
    return Decimal(str(value))


def audit(db, user, org, action, kind, ident, detail=""):
    db.add(AuditEvent(actor_user_id=user.id, organization_id=org, action=action,
                      resource_type=kind, resource_id=str(ident), detail=detail))


def get_warehouse(db, org, warehouse_id, membership=None):
    row = db.query(InventoryWarehouse).filter_by(id=warehouse_id, organization_id=org, is_active=True).first()
    if not row or (membership is not None and not can_access_branch(membership, row.branch_id)):
        raise HTTPException(404, "Warehouse not found")
    return row


def stock_balance(db, org, product_id, warehouse):
    warehouse_count = db.query(InventoryWarehouse).filter_by(
        organization_id=org, branch_id=warehouse.branch_id, is_active=True).count()
    q = db.query(func.coalesce(func.sum(InventoryStockMovement.quantity_delta), 0)).filter(
        InventoryStockMovement.organization_id == org,
        InventoryStockMovement.product_id == product_id,
        InventoryStockMovement.branch_id == warehouse.branch_id)
    if warehouse_count == 1:
        q = q.filter((InventoryStockMovement.warehouse_id == warehouse.id) | (InventoryStockMovement.warehouse_id.is_(None)))
    else:
        q = q.filter(InventoryStockMovement.warehouse_id == warehouse.id)
    return dec(q.scalar() or 0)


def active_reserved(db, org, warehouse_id, product_id):
    now = datetime.now(timezone.utc)
    rows = db.query(InventoryReservation).filter_by(organization_id=org, warehouse_id=warehouse_id,
        product_id=product_id, status="active").all()
    total = Decimal("0")
    for row in rows:
        exp = row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp > now:
            total += dec(row.quantity)
    return total


def warehouse_qty(db, org, warehouse, product_id):
    return stock_balance(db, org, product_id, warehouse)


class WarehouseIn(BaseModel):
    branch_id: str
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=180)


class TransferLineIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, le=Decimal("999999999999"))


class TransferIn(BaseModel):
    source_warehouse_id: int = Field(gt=0)
    destination_warehouse_id: int = Field(gt=0)
    lines: list[TransferLineIn] = Field(min_length=1, max_length=500)


class DispatchIn(BaseModel):
    tracking_reference: str = Field(default="", max_length=120)


class ReservationIn(BaseModel):
    warehouse_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    source_type: str = Field(pattern=r"^(sales_order|pos_order)$")
    source_reference: str = Field(min_length=1, max_length=100)
    quantity: Decimal = Field(gt=0)
    expires_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=100)


class BatchReceiptIn(BaseModel):
    warehouse_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    lot_number: str = Field(default="", max_length=100)
    serial_number: str = Field(default="", max_length=100)
    expiry_date: date | None = None
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def validate_serial_quantity(self):
        if self.serial_number and self.quantity != Decimal("1"):
            raise ValueError("serialized inventory must have quantity exactly one")
        return self


class BatchIssueIn(BaseModel):
    warehouse_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    method: str = Field(default="FEFO", pattern=r"^(FEFO|FIFO)$")
    idempotency_key: str = Field(min_length=8, max_length=100)


class StocktakeLineIn(BaseModel):
    product_id: int = Field(gt=0)
    counted_quantity: Decimal = Field(ge=0)


class StocktakeIn(BaseModel):
    warehouse_id: int = Field(gt=0)
    note: str = Field(default="", max_length=500)
    lines: list[StocktakeLineIn] = Field(min_length=1, max_length=1000)


class ReorderRuleIn(BaseModel):
    warehouse_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    minimum_quantity: Decimal = Field(ge=0)
    maximum_quantity: Decimal = Field(gt=0)
    lead_time_days: int = Field(default=7, ge=0, le=365)

    @model_validator(mode="after")
    def validate_range(self):
        if self.maximum_quantity < self.minimum_quantity:
            raise ValueError("maximum_quantity must be at least minimum_quantity")
        return self


class BatchStatusIn(BaseModel):
    status: str = Field(pattern=r"^(damaged|expired|quarantined)$")
    reason: str = Field(min_length=3, max_length=300)


class PriceListIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    currency: str = Field(default="KES", pattern=r"^[A-Z]{3}$")
    branch_id: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class PriceIn(BaseModel):
    product_id: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    promotion_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)


@router.get("/warehouses")
def list_warehouses(membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    q=db.query(InventoryWarehouse).filter_by(organization_id=membership.organization_id,is_active=True)
    allowed=branch_scope_ids(membership)
    if allowed is not None: q=q.filter(InventoryWarehouse.branch_id.in_(allowed)) if allowed else q.filter(False)
    return [{"id":w.id,"branch_id":w.branch_id,"code":w.code,"name":w.name} for w in q.order_by(InventoryWarehouse.name).all()]


@router.post("/warehouses",status_code=201)
def create_warehouse(payload:WarehouseIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    branch=db.query(Branch).filter_by(id=payload.branch_id,organization_id=membership.organization_id,is_active=True).first()
    if not branch or not can_access_branch(membership,branch.id): raise HTTPException(404,"Branch not found")
    if db.query(InventoryWarehouse).filter_by(organization_id=membership.organization_id,code=payload.code).first():
        raise HTTPException(409,"Warehouse code already exists")
    row=InventoryWarehouse(organization_id=membership.organization_id,branch_id=branch.id,code=payload.code,name=payload.name)
    db.add(row);db.flush();audit(db,user,membership.organization_id,"inventory.warehouse.created","inventory_warehouse",row.id);db.commit()
    return {"id":row.id,"branch_id":row.branch_id,"code":row.code,"name":row.name}


@router.post("/transfers",status_code=201)
def create_transfer(payload:TransferIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    src=get_warehouse(db,membership.organization_id,payload.source_warehouse_id,membership)
    dst=get_warehouse(db,membership.organization_id,payload.destination_warehouse_id,membership)
    if src.id==dst.id: raise HTTPException(422,"Source and destination warehouses must differ")
    if len({x.product_id for x in payload.lines}) != len(payload.lines): raise HTTPException(422,"Duplicate products are not allowed")
    row=InventoryTransfer(organization_id=membership.organization_id,transfer_number=f"TR-{uuid4().hex[:12].upper()}",
        source_warehouse_id=src.id,destination_warehouse_id=dst.id,created_by=user.id)
    db.add(row);db.flush()
    for line in payload.lines:
        product=db.query(InventoryProduct).filter_by(id=line.product_id,organization_id=membership.organization_id,is_active=True).first()
        if not product: raise HTTPException(404,"Product not found")
        db.add(InventoryTransferLine(organization_id=membership.organization_id,transfer_id=row.id,product_id=line.product_id,quantity=line.quantity.quantize(Q3)))
    db.flush();audit(db,user,membership.organization_id,"inventory.transfer.created","inventory_transfer",row.id);db.commit()
    return {"id":row.id,"transfer_number":row.transfer_number,"status":row.status}


@router.post("/transfers/{transfer_id}/dispatch")
def dispatch_transfer(transfer_id:int,payload:DispatchIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(InventoryTransfer).filter_by(id=transfer_id,organization_id=membership.organization_id).with_for_update().first()
    if not row: raise HTTPException(404,"Transfer not found")
    if row.status!="draft": raise HTTPException(409,"Only draft transfers can be dispatched")
    src=get_warehouse(db,membership.organization_id,row.source_warehouse_id,membership)
    lines=db.query(InventoryTransferLine).filter_by(transfer_id=row.id,organization_id=membership.organization_id).all()
    for line in lines:
        product=db.query(InventoryProduct).filter_by(id=line.product_id,organization_id=membership.organization_id).with_for_update().first()
        if not product: raise HTTPException(404,"Product not found")
        available=warehouse_qty(db,membership.organization_id,src,line.product_id)-active_reserved(db,membership.organization_id,src.id,line.product_id)
        if available < dec(line.quantity): raise HTTPException(409,f"Insufficient available stock for product {line.product_id}")
    for line in lines:
        db.add(InventoryStockMovement(organization_id=membership.organization_id,product_id=line.product_id,branch_id=src.branch_id,warehouse_id=src.id,
            quantity_delta=-dec(line.quantity),movement_type="transfer_out",reference=row.transfer_number,
            idempotency_key=f"transfer-{row.id}-{line.product_id}-out",created_by=user.id))
    row.status="in_transit";row.tracking_reference=payload.tracking_reference;row.dispatched_at=datetime.now(timezone.utc)
    audit(db,user,membership.organization_id,"inventory.transfer.dispatched","inventory_transfer",row.id);db.commit()
    return {"id":row.id,"status":row.status,"tracking_reference":row.tracking_reference}


@router.post("/transfers/{transfer_id}/receive")
def receive_transfer(transfer_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(InventoryTransfer).filter_by(id=transfer_id,organization_id=membership.organization_id).with_for_update().first()
    if not row: raise HTTPException(404,"Transfer not found")
    if row.status!="in_transit": raise HTTPException(409,"Only dispatched transfers can be received")
    dst=get_warehouse(db,membership.organization_id,row.destination_warehouse_id,membership)
    lines=db.query(InventoryTransferLine).filter_by(transfer_id=row.id,organization_id=membership.organization_id).all()
    for line in lines:
        db.add(InventoryStockMovement(organization_id=membership.organization_id,product_id=line.product_id,branch_id=dst.branch_id,warehouse_id=dst.id,
            quantity_delta=dec(line.quantity),movement_type="transfer_in",reference=row.transfer_number,
            idempotency_key=f"transfer-{row.id}-{line.product_id}-in",created_by=user.id))
    row.status="received";row.received_at=datetime.now(timezone.utc)
    audit(db,user,membership.organization_id,"inventory.transfer.received","inventory_transfer",row.id);db.commit()
    return {"id":row.id,"status":row.status,"received_at":row.received_at.isoformat()}


@router.get("/transfers")
def list_transfers(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    rows=db.query(InventoryTransfer).filter_by(organization_id=membership.organization_id).order_by(InventoryTransfer.id.desc()).limit(500).all()
    visible=[]
    for x in rows:
        source=db.query(InventoryWarehouse).filter_by(id=x.source_warehouse_id,organization_id=membership.organization_id).first()
        destination=db.query(InventoryWarehouse).filter_by(id=x.destination_warehouse_id,organization_id=membership.organization_id).first()
        if source and destination and can_access_branch(membership,source.branch_id) and can_access_branch(membership,destination.branch_id):
            visible.append({"id":x.id,"transfer_number":x.transfer_number,"status":x.status,"tracking_reference":x.tracking_reference,
                "source_warehouse_id":x.source_warehouse_id,"destination_warehouse_id":x.destination_warehouse_id})
    return visible


@router.post("/reservations",status_code=201)
def reserve_stock(payload:ReservationIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    wh=get_warehouse(db,membership.organization_id,payload.warehouse_id,membership)
    if payload.expires_at.tzinfo is None: raise HTTPException(422,"expires_at must include a timezone")
    if payload.expires_at<=datetime.now(timezone.utc): raise HTTPException(422,"Reservation expiry must be in the future")
    duplicate=db.query(InventoryReservation).filter_by(organization_id=membership.organization_id,idempotency_key=payload.idempotency_key).first()
    if duplicate:
        old_expiry=duplicate.expires_at if duplicate.expires_at.tzinfo else duplicate.expires_at.replace(tzinfo=timezone.utc)
        new_expiry=payload.expires_at.astimezone(timezone.utc)
        if (duplicate.product_id,duplicate.warehouse_id,duplicate.quantity,duplicate.source_type,duplicate.source_reference)!=(payload.product_id,wh.id,payload.quantity,payload.source_type,payload.source_reference) or old_expiry!=new_expiry:
            raise HTTPException(409,"Idempotency key reused with different reservation")
        return {"id":duplicate.id,"status":duplicate.status}
    product=db.query(InventoryProduct).filter_by(id=payload.product_id,organization_id=membership.organization_id,is_active=True).with_for_update().first()
    if not product: raise HTTPException(404,"Product not found")
    available=warehouse_qty(db,membership.organization_id,wh,payload.product_id)-active_reserved(db,membership.organization_id,wh.id,payload.product_id)
    if available < payload.quantity: raise HTTPException(409,"Insufficient available stock")
    row=InventoryReservation(organization_id=membership.organization_id,warehouse_id=wh.id,product_id=payload.product_id,
        source_type=payload.source_type,source_reference=payload.source_reference,quantity=payload.quantity.quantize(Q3),
        status="active",idempotency_key=payload.idempotency_key,expires_at=payload.expires_at,created_by=user.id)
    db.add(row);db.flush();audit(db,user,membership.organization_id,"inventory.stock.reserved","inventory_reservation",row.id);db.commit()
    return {"id":row.id,"status":row.status,"quantity":str(row.quantity),"expires_at":row.expires_at.isoformat()}


@router.post("/reservations/{reservation_id}/consume")
def consume_reservation(reservation_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    row=db.query(InventoryReservation).filter_by(id=reservation_id,organization_id=membership.organization_id).with_for_update().first()
    if not row: raise HTTPException(404,"Reservation not found")
    if row.status=="consumed": return {"id":row.id,"status":"consumed"}
    if row.status!="active": raise HTTPException(409,"Reservation is not active")
    expiry=row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expiry<=datetime.now(timezone.utc):
        row.status="expired";db.commit();raise HTTPException(409,"Reservation has expired")
    wh=get_warehouse(db,membership.organization_id,row.warehouse_id,membership)
    product=db.query(InventoryProduct).filter_by(id=row.product_id,organization_id=membership.organization_id).with_for_update().first()
    if not product: raise HTTPException(404,"Product not found")
    remaining=dec(row.quantity)
    batches=db.query(InventoryBatch).filter(InventoryBatch.organization_id==membership.organization_id,
        InventoryBatch.warehouse_id==wh.id,InventoryBatch.product_id==row.product_id,
        InventoryBatch.status=="available",InventoryBatch.quantity_on_hand>0).order_by(
        InventoryBatch.expiry_date.asc().nullslast(),InventoryBatch.created_at.asc()).with_for_update().all()
    for batch in batches:
        exp=batch.expiry_date
        if exp and (exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc))<datetime.now(timezone.utc): continue
        take=min(dec(batch.quantity_on_hand),remaining)
        batch.quantity_on_hand=dec(batch.quantity_on_hand)-take
        remaining-=take
        if remaining<=0: break
    if remaining>0 and batches: raise HTTPException(409,"Insufficient eligible batch quantity to fulfil reservation")
    db.add(InventoryStockMovement(organization_id=membership.organization_id,product_id=row.product_id,
        branch_id=wh.branch_id,warehouse_id=wh.id,quantity_delta=-dec(row.quantity),
        movement_type="reservation_consume",reference=f"reservation:{row.id}",
        idempotency_key=f"reservation-{row.id}-consume",created_by=user.id))
    row.status="consumed"
    audit(db,user,membership.organization_id,"inventory.stock.reservation_consumed","inventory_reservation",row.id)
    db.commit()
    return {"id":row.id,"status":row.status,"quantity":str(row.quantity)}


@router.post("/reservations/{reservation_id}/release")
def release_reservation(reservation_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(InventoryReservation).filter_by(id=reservation_id,organization_id=membership.organization_id).with_for_update().first()
    if not row: raise HTTPException(404,"Reservation not found")
    if row.status!="active": return {"id":row.id,"status":row.status}
    row.status="released";audit(db,user,membership.organization_id,"inventory.stock.reservation_released","inventory_reservation",row.id);db.commit()
    return {"id":row.id,"status":row.status}


@router.post("/reservations/expire")
def expire_reservations(membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    q=db.query(InventoryReservation).join(InventoryWarehouse,InventoryWarehouse.id==InventoryReservation.warehouse_id).filter(InventoryReservation.organization_id==membership.organization_id,InventoryReservation.status=="active")
    allowed=branch_scope_ids(membership)
    if allowed is not None: q=q.filter(InventoryWarehouse.branch_id.in_(allowed)) if allowed else q.filter(False)
    rows=q.all()
    now=datetime.now(timezone.utc);count=0
    for row in rows:
        exp=row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
        if exp<=now: row.status="expired";count+=1
    audit(db,user,membership.organization_id,"inventory.reservations.expired","inventory_reservation","batch",str(count));db.commit()
    return {"expired_count":count}


@router.get("/reservations")
def list_reservations(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    q=db.query(InventoryReservation).join(InventoryWarehouse,InventoryWarehouse.id==InventoryReservation.warehouse_id).filter(InventoryReservation.organization_id==membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None: q=q.filter(InventoryWarehouse.branch_id.in_(allowed)) if allowed else q.filter(False)
    rows=q.order_by(InventoryReservation.id.desc()).limit(1000).all()
    return [{"id":x.id,"warehouse_id":x.warehouse_id,"product_id":x.product_id,"source_type":x.source_type,
        "source_reference":x.source_reference,"quantity":str(x.quantity),"status":x.status,"expires_at":x.expires_at.isoformat()} for x in rows]


@router.post("/batches/receive",status_code=201)
def receive_batch(payload:BatchReceiptIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    wh=get_warehouse(db,membership.organization_id,payload.warehouse_id,membership)
    product=db.query(InventoryProduct).filter_by(id=payload.product_id,organization_id=membership.organization_id,is_active=True).first()
    if not product: raise HTTPException(404,"Product not found")
    if payload.expiry_date and payload.expiry_date<date.today(): raise HTTPException(422,"Cannot receive an already expired batch")
    if payload.serial_number and payload.quantity!=Decimal("1"): raise HTTPException(422,"A serialized unit must have quantity one")
    if payload.serial_number and db.query(InventoryBatch).filter_by(organization_id=membership.organization_id,serial_number=payload.serial_number).first():
        raise HTTPException(409,"Serial number already exists")
    existing=db.query(InventoryStockMovement).filter_by(organization_id=membership.organization_id,idempotency_key=payload.idempotency_key).first()
    if existing:
        if existing.product_id!=payload.product_id or existing.warehouse_id!=wh.id or existing.quantity_delta!=payload.quantity.quantize(Q3) or existing.movement_type!="batch_receipt":
            raise HTTPException(409,"Receipt idempotency key reused with different content")
        batch_id=existing.reference.split(":",1)[1] if existing.reference.startswith("batch:") else None
        return {"id":int(batch_id) if batch_id and batch_id.isdigit() else None,"status":"already_applied","movement_id":existing.id}
    row=InventoryBatch(organization_id=membership.organization_id,warehouse_id=wh.id,product_id=product.id,lot_number=payload.lot_number,
        serial_number=payload.serial_number or None,expiry_date=datetime.combine(payload.expiry_date,datetime.min.time(),tzinfo=timezone.utc) if payload.expiry_date else None,
        quantity_on_hand=payload.quantity.quantize(Q3),unit_cost=payload.unit_cost,status="available")
    db.add(row);db.flush()
    db.add(InventoryStockMovement(organization_id=membership.organization_id,product_id=product.id,branch_id=wh.branch_id,warehouse_id=wh.id,
        quantity_delta=payload.quantity.quantize(Q3),movement_type="batch_receipt",reference=f"batch:{row.id}",
        idempotency_key=payload.idempotency_key,created_by=user.id))
    audit(db,user,membership.organization_id,"inventory.batch.received","inventory_batch",row.id);db.commit()
    return {"id":row.id,"product_id":row.product_id,"quantity":str(row.quantity_on_hand),"status":row.status}


@router.post("/batches/issue")
def issue_batches(payload:BatchIssueIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    wh=get_warehouse(db,membership.organization_id,payload.warehouse_id,membership)
    product=db.query(InventoryProduct).filter_by(id=payload.product_id,organization_id=membership.organization_id,is_active=True).with_for_update().first()
    if not product: raise HTTPException(404,"Product not found")
    dup=db.query(InventoryStockMovement).filter_by(organization_id=membership.organization_id,idempotency_key=payload.idempotency_key).first()
    if dup:
        if dup.product_id!=payload.product_id or dup.warehouse_id!=wh.id or dup.quantity_delta!=-payload.quantity.quantize(Q3) or dup.movement_type!="batch_issue" or dup.reference!=f"{payload.method} issue":
            raise HTTPException(409,"Issue idempotency key reused with different content")
        return {"status":"already_applied","movement_id":dup.id}
    available=warehouse_qty(db,membership.organization_id,wh,payload.product_id)-active_reserved(db,membership.organization_id,wh.id,payload.product_id)
    if available<payload.quantity: raise HTTPException(409,"Insufficient unreserved stock")
    today=datetime.now(timezone.utc)
    q=db.query(InventoryBatch).filter(InventoryBatch.organization_id==membership.organization_id,
        InventoryBatch.warehouse_id==wh.id,InventoryBatch.product_id==payload.product_id,
        InventoryBatch.status=="available",InventoryBatch.quantity_on_hand>0)
    q=q.filter((InventoryBatch.expiry_date.is_(None)) | (InventoryBatch.expiry_date>=today))
    q=q.order_by(InventoryBatch.expiry_date.asc().nullslast(),InventoryBatch.created_at.asc()) if payload.method=="FEFO" else q.order_by(InventoryBatch.created_at.asc())
    batches=q.with_for_update().all();remaining=payload.quantity
    for batch in batches:
        take=min(dec(batch.quantity_on_hand),remaining)
        if take>0: batch.quantity_on_hand=(dec(batch.quantity_on_hand)-take).quantize(Q3);remaining-=take
        if remaining<=0: break
    if remaining>0: raise HTTPException(409,"Insufficient eligible batch stock")
    db.add(InventoryStockMovement(organization_id=membership.organization_id,product_id=payload.product_id,branch_id=wh.branch_id,warehouse_id=wh.id,
        quantity_delta=-payload.quantity.quantize(Q3),movement_type="batch_issue",reference=f"{payload.method} issue",
        idempotency_key=payload.idempotency_key,created_by=user.id))
    audit(db,user,membership.organization_id,"inventory.batch.issued","inventory_product",payload.product_id,f"method:{payload.method};quantity:{payload.quantity}")
    db.commit()
    return {"status":"issued","quantity":str(payload.quantity.quantize(Q3)),"method":payload.method}


@router.post("/batches/{batch_id}/quarantine")
def quarantine_batch(batch_id:int,reason:str=Query(min_length=3,max_length=300),membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(InventoryBatch).filter_by(id=batch_id,organization_id=membership.organization_id).with_for_update().first()
    if not row: raise HTTPException(404,"Batch not found")
    if row.status!="available": raise HTTPException(409,"Only available batches can be quarantined")
    row.status="quarantined";audit(db,user,membership.organization_id,"inventory.batch.quarantined","inventory_batch",row.id,reason);db.commit()
    return {"id":row.id,"status":row.status}


@router.patch("/batches/{batch_id}/status")
def update_batch_status(batch_id:int,payload:BatchStatusIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(InventoryBatch).filter_by(id=batch_id,organization_id=membership.organization_id).with_for_update().first()
    if not row: raise HTTPException(404,"Batch not found")
    if row.status not in ("available","quarantined"): raise HTTPException(409,"Only available or quarantined batches can be dispositioned")
    if payload.status=="expired":
        if not row.expiry_date: raise HTTPException(422,"An expiry date is required before marking a batch expired")
        exp=row.expiry_date if row.expiry_date.tzinfo else row.expiry_date.replace(tzinfo=timezone.utc)
        if exp>datetime.now(timezone.utc): raise HTTPException(422,"Batch has not reached its expiry date")
    if row.status=="available" and payload.status in ("damaged","expired","quarantined") and dec(row.quantity_on_hand)>0:
        wh=get_warehouse(db,membership.organization_id,row.warehouse_id,membership)
        db.add(InventoryStockMovement(organization_id=membership.organization_id,product_id=row.product_id,
            branch_id=wh.branch_id,warehouse_id=wh.id,quantity_delta=-dec(row.quantity_on_hand),
            movement_type="batch_disposition",reference=f"batch:{row.id}:{payload.status}",
            idempotency_key=f"batch-{row.id}-disposition",created_by=user.id))
    row.status=payload.status
    audit(db,user,membership.organization_id,"inventory.batch.dispositioned","inventory_batch",row.id,payload.reason)
    db.commit()
    return {"id":row.id,"status":row.status}


@router.get("/batches")
def list_batches(product_id:int|None=None,warehouse_id:int|None=None,membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    q=db.query(InventoryBatch).join(InventoryWarehouse,InventoryWarehouse.id==InventoryBatch.warehouse_id).filter(InventoryBatch.organization_id==membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None: q=q.filter(InventoryWarehouse.branch_id.in_(allowed)) if allowed else q.filter(False)
    if product_id:q=q.filter(InventoryBatch.product_id==product_id)
    if warehouse_id:
        wh=get_warehouse(db,membership.organization_id,warehouse_id,membership);q=q.filter(InventoryBatch.warehouse_id==wh.id)
    rows=q.order_by(InventoryBatch.expiry_date.asc().nullslast(),InventoryBatch.id).limit(2000).all()
    return [{"id":x.id,"warehouse_id":x.warehouse_id,"product_id":x.product_id,"lot_number":x.lot_number,"serial_number":x.serial_number,
        "expiry_date":x.expiry_date.date().isoformat() if x.expiry_date else None,"quantity_on_hand":str(x.quantity_on_hand),
        "unit_cost":str(x.unit_cost),"status":x.status} for x in rows]


@router.post("/stocktakes",status_code=201)
def create_stocktake(payload:StocktakeIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    wh=get_warehouse(db,membership.organization_id,payload.warehouse_id,membership)
    if len({x.product_id for x in payload.lines})!=len(payload.lines):raise HTTPException(422,"Duplicate stocktake products")
    row=InventoryStocktake(organization_id=membership.organization_id,warehouse_id=wh.id,status="pending_approval",note=payload.note,created_by=user.id)
    db.add(row);db.flush()
    for item in payload.lines:
        if not db.query(InventoryProduct).filter_by(id=item.product_id,organization_id=membership.organization_id).first():raise HTTPException(404,"Product not found")
        expected=warehouse_qty(db,membership.organization_id,wh,item.product_id)
        db.add(InventoryStocktakeLine(organization_id=membership.organization_id,stocktake_id=row.id,product_id=item.product_id,
            expected_quantity=expected,counted_quantity=item.counted_quantity.quantize(Q3)))
    audit(db,user,membership.organization_id,"inventory.stocktake.created","inventory_stocktake",row.id);db.commit()
    return {"id":row.id,"status":row.status}


@router.post("/stocktakes/{stocktake_id}/approve")
def approve_stocktake(stocktake_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(InventoryStocktake).filter_by(id=stocktake_id,organization_id=membership.organization_id).with_for_update().first()
    if not row:raise HTTPException(404,"Stocktake not found")
    if row.status!="pending_approval":raise HTTPException(409,"Stocktake is not awaiting approval")
    if row.created_by==user.id:raise HTTPException(403,"Maker cannot approve own stocktake")
    wh=get_warehouse(db,membership.organization_id,row.warehouse_id,membership)
    lines=db.query(InventoryStocktakeLine).filter_by(organization_id=membership.organization_id,stocktake_id=row.id).all()
    for line in lines:
        current_quantity=warehouse_qty(db,membership.organization_id,wh,line.product_id)
        if current_quantity != dec(line.expected_quantity):
            raise HTTPException(409,f"Stock changed after count for product {line.product_id}; recount before approval")
        delta=dec(line.counted_quantity)-dec(line.expected_quantity)
        if delta:
            db.add(InventoryStockMovement(organization_id=membership.organization_id,product_id=line.product_id,branch_id=wh.branch_id,warehouse_id=wh.id,
                quantity_delta=delta,movement_type="stocktake_adjustment",reference=f"stocktake:{row.id}",
                idempotency_key=f"stocktake-{row.id}-{line.product_id}",created_by=user.id))
    row.status="approved";row.approved_by=user.id;row.approved_at=datetime.now(timezone.utc)
    audit(db,user,membership.organization_id,"inventory.stocktake.approved","inventory_stocktake",row.id);db.commit()
    return {"id":row.id,"status":row.status}


@router.get("/stocktakes")
def list_stocktakes(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    q=db.query(InventoryStocktake).join(InventoryWarehouse,InventoryWarehouse.id==InventoryStocktake.warehouse_id).filter(InventoryStocktake.organization_id==membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None: q=q.filter(InventoryWarehouse.branch_id.in_(allowed)) if allowed else q.filter(False)
    rows=q.order_by(InventoryStocktake.id.desc()).limit(500).all()
    return [{"id":x.id,"warehouse_id":x.warehouse_id,"status":x.status,"note":x.note,"created_at":x.created_at.isoformat()} for x in rows]


@router.put("/reorder-rules",status_code=201)
def upsert_reorder_rule(payload:ReorderRuleIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    if payload.maximum_quantity<payload.minimum_quantity:raise HTTPException(422,"Maximum quantity must be at least minimum quantity")
    wh=get_warehouse(db,membership.organization_id,payload.warehouse_id,membership)
    if not db.query(InventoryProduct).filter_by(id=payload.product_id,organization_id=membership.organization_id).first():raise HTTPException(404,"Product not found")
    row=db.query(InventoryReorderRule).filter_by(organization_id=membership.organization_id,warehouse_id=wh.id,product_id=payload.product_id).first()
    if not row:row=InventoryReorderRule(organization_id=membership.organization_id,warehouse_id=wh.id,product_id=payload.product_id);db.add(row)
    row.minimum_quantity=payload.minimum_quantity;row.maximum_quantity=payload.maximum_quantity;row.lead_time_days=payload.lead_time_days;row.is_active=True
    audit(db,user,membership.organization_id,"inventory.reorder_rule.updated","inventory_reorder_rule",row.id or "new");db.commit()
    return {"id":row.id,"minimum_quantity":str(row.minimum_quantity),"maximum_quantity":str(row.maximum_quantity)}


@router.get("/replenishment")
def replenishment(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    rules=db.query(InventoryReorderRule).join(InventoryWarehouse,InventoryWarehouse.id==InventoryReorderRule.warehouse_id).filter(InventoryReorderRule.organization_id==membership.organization_id,InventoryReorderRule.is_active==True).all()
    allowed=branch_scope_ids(membership)
    if allowed is not None: rules=[r for r in rules if db.query(InventoryWarehouse).filter_by(id=r.warehouse_id).first() and db.query(InventoryWarehouse).filter_by(id=r.warehouse_id).first().branch_id in allowed]
    result=[]
    for rule in rules:
        wh=get_warehouse(db,membership.organization_id,rule.warehouse_id,membership)
        if allowed is not None and wh.branch_id not in allowed: continue
        on_hand=warehouse_qty(db,membership.organization_id,wh,rule.product_id)
        reserved=active_reserved(db,membership.organization_id,wh.id,rule.product_id)
        available=on_hand-reserved
        if available<=dec(rule.minimum_quantity):
            suggested=max(Decimal("0"),dec(rule.maximum_quantity)-available).quantize(Q3)
            product=db.query(InventoryProduct).filter_by(id=rule.product_id,organization_id=membership.organization_id).first()
            result.append({"warehouse_id":wh.id,"product_id":rule.product_id,"sku":product.sku if product else "",
                "name":product.name if product else "","on_hand":str(on_hand),"reserved":str(reserved),
                "available":str(available),"suggested_order_quantity":str(suggested),"lead_time_days":rule.lead_time_days})
    return result


@router.get("/forecast")
def demand_forecast(days:int=Query(default=30,ge=7,le=365),membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    cutoff=datetime.now(timezone.utc)-timedelta(days=days)
    products=db.query(InventoryProduct).filter_by(organization_id=membership.organization_id,is_active=True).all()
    result=[]
    allowed=branch_scope_ids(membership)
    for product in products:
        issue_query=db.query(func.coalesce(func.sum(-InventoryStockMovement.quantity_delta),0)).filter(
            InventoryStockMovement.organization_id==membership.organization_id,InventoryStockMovement.product_id==product.id,
            InventoryStockMovement.quantity_delta<0,InventoryStockMovement.movement_type.in_(["issue","batch_issue","pos_sale","sale"]),InventoryStockMovement.created_at>=cutoff)
        if allowed is not None: issue_query=issue_query.filter(InventoryStockMovement.branch_id.in_(allowed)) if allowed else issue_query.filter(False)
        issues=issue_query.scalar()
        daily=dec(issues or 0)/Decimal(days)
        result.append({"product_id":product.id,"sku":product.sku,"name":product.name,"historical_daily_demand":str(daily.quantize(Q3)),
            "forecast_next_30_days":str((daily*Decimal(30)).quantize(Q3)),"method":"simple_moving_average"})
    return result


@router.post("/price-lists",status_code=201)
def create_price_list(payload:PriceListIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    if payload.starts_at and payload.ends_at and payload.ends_at<=payload.starts_at:raise HTTPException(422,"Price list end must follow start")
    if payload.branch_id:
        branch=db.query(Branch).filter_by(id=payload.branch_id,organization_id=membership.organization_id,is_active=True).first()
        if not branch or not can_access_branch(membership,branch.id):raise HTTPException(404,"Branch not found")
    row=InventoryPriceList(organization_id=membership.organization_id,**payload.model_dump())
    db.add(row);db.flush();audit(db,user,membership.organization_id,"inventory.price_list.created","inventory_price_list",row.id);db.commit()
    return {"id":row.id,"name":row.name,"currency":row.currency,"branch_id":row.branch_id}


@router.put("/price-lists/{price_list_id}/prices",status_code=201)
def set_price(price_list_id:int,payload:PriceIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    pl=db.query(InventoryPriceList).filter_by(id=price_list_id,organization_id=membership.organization_id,is_active=True).first()
    if not pl:raise HTTPException(404,"Price list not found")
    if not db.query(InventoryProduct).filter_by(id=payload.product_id,organization_id=membership.organization_id).first():raise HTTPException(404,"Product not found")
    row=db.query(InventoryPrice).filter_by(organization_id=membership.organization_id,price_list_id=pl.id,product_id=payload.product_id).first()
    if not row:row=InventoryPrice(organization_id=membership.organization_id,price_list_id=pl.id,product_id=payload.product_id);db.add(row)
    row.unit_price=payload.unit_price.quantize(MONEY,rounding=ROUND_HALF_UP);row.promotion_percent=payload.promotion_percent
    audit(db,user,membership.organization_id,"inventory.price.updated","inventory_price",row.id or "new");db.commit()
    return {"id":row.id,"unit_price":str(row.unit_price),"promotion_percent":str(row.promotion_percent)}


@router.get("/price-lists")
def list_price_lists(branch_id:str|None=None,membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    q=db.query(InventoryPriceList).filter_by(organization_id=membership.organization_id,is_active=True)
    allowed=branch_scope_ids(membership)
    if branch_id:
        if not can_access_branch(membership,branch_id):raise HTTPException(404,"Price list not found")
        q=q.filter((InventoryPriceList.branch_id==None)|(InventoryPriceList.branch_id==branch_id))
    elif allowed is not None:
        q=q.filter((InventoryPriceList.branch_id==None)|(InventoryPriceList.branch_id.in_(allowed))) if allowed else q.filter(InventoryPriceList.branch_id==None)
    return [{"id":p.id,"name":p.name,"currency":p.currency,"branch_id":p.branch_id,"starts_at":p.starts_at.isoformat() if p.starts_at else None,
        "ends_at":p.ends_at.isoformat() if p.ends_at else None} for p in q.all()]


@router.get("/warehouses/{warehouse_id}/stock")
def warehouse_stock(warehouse_id:int,membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    wh=get_warehouse(db,membership.organization_id,warehouse_id,membership)
    rows=db.query(InventoryProduct).filter_by(organization_id=membership.organization_id,is_active=True).order_by(InventoryProduct.name).all()
    result=[]
    for product in rows:
        on_hand=warehouse_qty(db,membership.organization_id,wh,product.id)
        reserved=active_reserved(db,membership.organization_id,wh.id,product.id)
        if on_hand or reserved:
            result.append({"warehouse_id":wh.id,"branch_id":wh.branch_id,"product_id":product.id,"sku":product.sku,
                "name":product.name,"on_hand":str(on_hand),"reserved":str(reserved),"available":str(on_hand-reserved)})
    return result


@router.get("/price-lists/{price_list_id}/prices")
def get_price_list_prices(price_list_id:int,membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    pl=db.query(InventoryPriceList).filter_by(id=price_list_id,organization_id=membership.organization_id,is_active=True).first()
    if not pl or (pl.branch_id and not can_access_branch(membership,pl.branch_id)): raise HTTPException(404,"Price list not found")
    rows=db.query(InventoryPrice,InventoryProduct).join(InventoryProduct,InventoryProduct.id==InventoryPrice.product_id).filter(
        InventoryPrice.organization_id==membership.organization_id,InventoryPrice.price_list_id==pl.id).all()
    return [{"product_id":p.id,"sku":p.sku,"name":p.name,"unit_price":str(price.unit_price),
        "promotion_percent":str(price.promotion_percent),
        "effective_price":str((dec(price.unit_price)*(Decimal("1")-dec(price.promotion_percent)/Decimal("100"))).quantize(MONEY,rounding=ROUND_HALF_UP))}
        for price,p in rows]


@router.get("/valuation")
def inventory_valuation(method:str=Query(default="weighted_average",pattern=r"^(weighted_average|fifo)$"),membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    batches=db.query(InventoryBatch).join(InventoryWarehouse,InventoryWarehouse.id==InventoryBatch.warehouse_id).filter(InventoryBatch.organization_id==membership.organization_id,InventoryBatch.status=="available").all()
    allowed=branch_scope_ids(membership)
    if allowed is not None: batches=[b for b in batches if db.query(InventoryWarehouse).filter_by(id=b.warehouse_id).first() and db.query(InventoryWarehouse).filter_by(id=b.warehouse_id).first().branch_id in allowed]
    by_product={}
    for b in batches:
        qty=dec(b.quantity_on_hand)
        if qty<=0:continue
        item=by_product.setdefault(b.product_id,{"quantity":Decimal("0"),"value":Decimal("0"),"layers":[]})
        item["quantity"]+=qty;item["value"]+=qty*dec(b.unit_cost);item["layers"].append((b.created_at,qty,dec(b.unit_cost)))
    out=[]
    for pid,item in by_product.items():
        if method=="weighted_average":
            value=item["value"]
        else:
            # FIFO valuation uses the currently remaining receipt layers, oldest receipt first.
            value=sum(q*c for _,q,c in sorted(item["layers"],key=lambda x:x[0]))
        out.append({"product_id":pid,"quantity":str(item["quantity"].quantize(Q3)),"unit_cost":str((item["value"]/item["quantity"]).quantize(MONEY) if item["quantity"] else "0"),
            "inventory_value":str(value.quantize(MONEY)),"method":method})
    return {"method":method,"currency":"organization_currency","items":out,"total_value":str(sum(dec(x["inventory_value"]) for x in out).quantize(MONEY))}


@router.get("/dashboard")
def inventory_dashboard(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    warehouses=db.query(InventoryWarehouse).filter_by(organization_id=membership.organization_id,is_active=True).all()
    allowed=branch_scope_ids(membership)
    warehouses=[w for w in warehouses if can_access_branch(membership,w.branch_id)]
    products=db.query(InventoryProduct).filter_by(organization_id=membership.organization_id,is_active=True).count()
    low=0
    rules=db.query(InventoryReorderRule).join(InventoryWarehouse,InventoryWarehouse.id==InventoryReorderRule.warehouse_id).filter(InventoryReorderRule.organization_id==membership.organization_id,InventoryReorderRule.is_active==True).all()
    allowed=branch_scope_ids(membership)
    for rule in rules:
        wh=get_warehouse(db,membership.organization_id,rule.warehouse_id,membership)
        if allowed is not None and wh.branch_id not in allowed: continue
        if warehouse_qty(db,membership.organization_id,wh,rule.product_id)-active_reserved(db,membership.organization_id,wh.id,rule.product_id) <= dec(rule.minimum_quantity):
            low += 1
    batch_query=db.query(InventoryBatch).join(InventoryWarehouse,InventoryWarehouse.id==InventoryBatch.warehouse_id).filter(InventoryBatch.organization_id==membership.organization_id)
    transfer_query=db.query(InventoryTransfer).filter_by(organization_id=membership.organization_id,status="in_transit")
    if allowed is not None:
        batch_query=batch_query.filter(InventoryWarehouse.branch_id.in_(allowed)) if allowed else batch_query.filter(False)
        transfer_query=transfer_query.join(InventoryWarehouse,InventoryWarehouse.id==InventoryTransfer.source_warehouse_id).filter(InventoryWarehouse.branch_id.in_(allowed)) if allowed else transfer_query.filter(False)
    expired=batch_query.filter(InventoryBatch.status=="available",InventoryBatch.expiry_date<datetime.now(timezone.utc)).count()
    quarantined=batch_query.filter(InventoryBatch.status=="quarantined").count()
    in_transit=transfer_query.count()
    return {"active_products":products,"warehouses":len(warehouses),"low_stock_rule_count":low,
        "expired_batches":expired,"quarantined_batches":quarantined,"transfers_in_transit":in_transit}


@router.get("/alerts")
def inventory_alerts(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    now=datetime.now(timezone.utc)
    batch_query=db.query(InventoryBatch).join(InventoryWarehouse,InventoryWarehouse.id==InventoryBatch.warehouse_id).filter(InventoryBatch.organization_id==membership.organization_id,InventoryBatch.status=="available")
    allowed=branch_scope_ids(membership)
    if allowed is not None: batch_query=batch_query.filter(InventoryWarehouse.branch_id.in_(allowed)) if allowed else batch_query.filter(False)
    batches=batch_query.all()
    alerts=[]
    for b in batches:
        if b.expiry_date:
            exp=b.expiry_date if b.expiry_date.tzinfo else b.expiry_date.replace(tzinfo=timezone.utc)
            if exp<now:alerts.append({"type":"expired_stock","batch_id":b.id,"product_id":b.product_id,"quantity":str(b.quantity_on_hand)})
            elif exp<=now+timedelta(days=30):alerts.append({"type":"expiring_soon","batch_id":b.id,"product_id":b.product_id,"expiry_date":exp.date().isoformat()})
    for item in replenishment(membership,db):
        alerts.append({"type":"low_stock","product_id":item["product_id"],"warehouse_id":item["warehouse_id"],"available":item["available"]})
    return alerts
