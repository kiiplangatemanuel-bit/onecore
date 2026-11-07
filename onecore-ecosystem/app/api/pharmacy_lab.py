"""Encrypted, tenant-scoped pharmacy and laboratory operations.

Clinical payloads are stored in HealthcareResource using the healthcare Fernet
boundary. Stock movements remain in the shared append-only inventory ledger.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib, hmac, secrets, uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import (
    User, Membership, Branch, HealthcarePatient, HealthcareEncounter,
    HealthcareResource, HealthcareEvent, AuditEvent, InventoryProduct,
    InventoryStockMovement, ProcurementSupplier, ProcurementPurchaseOrder,
    ProcurementPurchaseOrderLine,
)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import can_access_branch, branch_scope_ids
from app.api.healthcare_hospital import (
    _create, _resource, _payload, _view, _need, _patient_access, _event, _audit,
    _money, _required_text,
)
from app.api.healthcare_privacy import _require, _patient, encrypt, decrypt

router = APIRouter(prefix="/api/v1", tags=["Pharmacy and laboratory"])
NOW = lambda: datetime.now(timezone.utc)
PHARMACY_ROLES = {"pharmacist", "healthcare_admin"}
LAB_ROLES = {"lab_technician", "healthcare_admin"}


def _decimal(value, name, positive=False, places=3):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(422, f"{name} must be a valid decimal")
    if not result.is_finite() or (positive and result <= 0) or abs(result) > Decimal("999999999"):
        raise HTTPException(422, f"{name} is outside the supported range")
    quantum = Decimal("1").scaleb(-places)
    if result.quantize(quantum) != result:
        raise HTTPException(422, f"{name} supports at most {places} decimal places")
    return result


def _date(value, name):
    try:
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    except (ValueError, TypeError):
        raise HTTPException(422, f"{name} must be an ISO date")


def _audit_action(db, m, u, action, resource_type, resource_id, detail=""):
    db.add(AuditEvent(organization_id=m.organization_id, actor_user_id=u.id,
        action=action, resource_type=resource_type, resource_id=str(resource_id),
        detail=str(detail)[:1000]))


def _update(row, data, u, status=None):
    row.encrypted_payload = encrypt(data)
    row.updated_by = u.id
    row.updated_at = NOW()
    if status is not None:
        row.status = status


def _resource_list(db, m, kind, branch_id=None, patient_id=None, status=None, limit=500):
    q = db.query(HealthcareResource).filter_by(
        organization_id=m.organization_id, resource_type=kind)
    global_kinds={"pharmacy_medicine","pharmacy_safety_rule","lab_test","lab_panel"}
    if branch_id is not None:
        if not can_access_branch(m, branch_id):
            raise HTTPException(404, "Resource not found")
        q = q.filter(HealthcareResource.branch_id == branch_id)
    elif kind not in global_kinds:
        allowed = branch_scope_ids(m)
        if allowed is not None:
            if not allowed:
                return []
            q = q.filter(or_(HealthcareResource.branch_id.is_(None),
                             HealthcareResource.branch_id.in_(allowed)))
    if patient_id is not None:
        q = q.filter(HealthcareResource.patient_id == patient_id)
    if status is not None:
        q = q.filter(HealthcareResource.status == status)
    return q.order_by(HealthcareResource.created_at.desc(), HealthcareResource.id.desc()).limit(limit).all()


def _get(db, m, rid, kind, lock=False):
    if kind in {"pharmacy_medicine","pharmacy_safety_rule","lab_test","lab_panel"}:
        q=db.query(HealthcareResource).filter_by(id=rid,organization_id=m.organization_id,resource_type=kind)
        row=(q.with_for_update() if lock else q).first()
        if not row:raise HTTPException(404,"Resource not found")
        return row
    return _resource(db, m, rid, kind, lock=lock)


def _medicine(db, m, medicine_id):
    row = _get(db, m, medicine_id, "pharmacy_medicine")
    if row.status != "active":
        raise HTTPException(404, "Active medicine not found")
    return row, _payload(row)


def _batch(db, m, batch_id, lock=False):
    row = _get(db, m, batch_id, "pharmacy_batch", lock=lock)
    return row, _payload(row)


def _need_any(db,m,u,action):
    allowed=branch_scope_ids(m)
    branches=[None] if allowed is None else allowed
    if not branches:raise HTTPException(403,"No branch access is assigned")
    for branch in branches:
        try:
            return _need(db,m,u,action,branch)
        except HTTPException as exc:
            if exc.status_code!=403:raise
    raise HTTPException(403,"Healthcare role does not grant this action in the assigned branches")


def _patient_read(db, m, u, patient_id):
    return _patient_access(db, m, u, patient_id, "clinical.read", write=False)


def _patient_write(db, m, u, patient_id):
    return _patient_access(db, m, u, patient_id, "clinical.write", write=True)


def _patient_event(db, m, u, patient, action, detail, resource_id=None, key=None):
    _audit(db, m, u, patient, action, detail.get("reason", "") if isinstance(detail, dict) else str(detail))
    _event(db, m, u, patient.id, patient.branch_id, action, detail, resource_id, key)


def _movement(db, m, u, product_id, branch_id, delta, kind, reference, key):
    existing = db.query(InventoryStockMovement).filter_by(
        organization_id=m.organization_id, idempotency_key=key).first()
    if existing:
        if existing.product_id != product_id or existing.quantity_delta != delta or existing.branch_id != branch_id:
            raise HTTPException(409, "Stock movement idempotency key conflicts with a previous movement")
        return existing
    row = InventoryStockMovement(organization_id=m.organization_id, product_id=product_id,
        branch_id=branch_id, quantity_delta=delta, movement_type=kind,
        reference=reference[:120], idempotency_key=key[:100], created_by=u.id)
    db.add(row)
    return row


def _controlled_event(db, m, u, medicine_id, batch_id, patient_id, event_type,
                      quantity, reason, witness_id=None, parent_id=None, branch_id=None):
    data = {"medicine_id": medicine_id, "batch_id": batch_id, "event_type": event_type,
        "quantity": str(quantity), "reason": reason, "actor_id": u.id,
        "witness_id": witness_id, "occurred_at": NOW().isoformat()}
    row = _create(db, m, u, "pharmacy_controlled_event", data,
        branch_id=branch_id, patient_id=patient_id, parent_id=parent_id,
        status="recorded", idempotency_key=None)
    return row


def _verifier(db, m, verifier_id, branch_id):
    if verifier_id == 0:
        raise HTTPException(422, "A second verifier is required")
    target = db.query(User).filter_by(id=verifier_id, is_active=True).first()
    member = db.query(Membership).filter_by(
        organization_id=m.organization_id, user_id=verifier_id, is_active=True).first()
    if not target or not member:
        raise HTTPException(403, "Verifier must be an active member of this organization")
    roles, = (set(),)
    from app.api.healthcare_hospital import _roles
    roles = _roles(db, m, target, branch_id)
    if not roles.intersection({"pharmacist", "healthcare_admin"}):
        raise HTTPException(403, "Verifier must have pharmacist or healthcare administrator role")
    return target


def _active_patient_medicine_ids(db,m,patient_id):
    current=set()
    for rx in _resource_list(db,m,"pharmacy_prescription",patient_id=patient_id,limit=1000):
        if rx.status not in {"active","partially_dispensed"}:
            continue
        data=_payload(rx)
        if _date(data.get("valid_until"),"valid_until")<date.today():
            continue
        for line in data.get("lines",[]):
            authorized=Decimal(line["quantity_prescribed"])*(1+int(line.get("refills_allowed",0)))
            if Decimal(line.get("quantity_dispensed","0"))<authorized:
                current.add(int(line["medicine_id"]))
    return current


def _check_drug_safety(db, m, patient_id, medicine_ids, concurrent_ids=None):
    warnings, blockers = [], []
    new_ids=set(medicine_ids);concurrent_ids=set(concurrent_ids or set())
    allergies = _resource_list(db, m, "pharmacy_allergy", patient_id=patient_id, limit=1000)
    for allergy in allergies:
        data = _payload(allergy)
        if data.get("status", "active") != "active":
            continue
        allergen = data.get("allergen", "").casefold()
        for mid in medicine_ids:
            _, med = _medicine(db, m, mid)
            known_names = {str(med.get("generic_name", "")).casefold(),
                           str(med.get("brand_name", "")).casefold(),
                           str(med.get("active_ingredient", "")).casefold()}
            if allergen and allergen in known_names:
                item = {"type": "allergy", "medicine_id": mid, "allergen": data.get("allergen"),
                        "reaction": data.get("reaction"), "severity": data.get("severity", "unknown")}
                (blockers if item["severity"] == "severe" else warnings).append(item)
    rules = _resource_list(db, m, "pharmacy_safety_rule", limit=1000)
    for rule in rules:
        data = _payload(rule)
        if data.get("is_active", True) is not True:
            continue
        a, b = data.get("medicine_a_id"), data.get("medicine_b_id")
        hit = (data.get("rule_type") == "allergy" and a in new_ids) or (
            data.get("rule_type") == "interaction" and
            ((a in new_ids and b in new_ids) or
             (a in new_ids and b in concurrent_ids) or
             (b in new_ids and a in concurrent_ids)))
        if hit:
            item = {"type": data.get("rule_type"), "medicine_ids": [a, b],
                    "description": data.get("description"), "severity": data.get("severity", "warning")}
            (blockers if item["severity"] == "block" else warnings).append(item)
    if blockers:
        raise HTTPException(422, {"message": "Prescription blocked by configured patient-safety rules",
                                  "blockers": blockers, "warnings": warnings})
    return warnings


# ---------------- Pharmacy catalogue and batch inventory ----------------

@router.post("/pharmacy/medicines", status_code=201)
def create_pharmacy_medicine(payload: dict, m=Depends(active_membership),
    u: User=Depends(current_user), db: Session=Depends(get_db)):
    _need_any(db, m, u, "pharmacy.manage")
    sku = _required_text(payload, "sku", 80).upper()
    generic = _required_text(payload, "generic_name")
    form = _required_text(payload, "dosage_form", 60)
    route = _required_text(payload, "route", 40)
    unit = _required_text(payload, "unit", 24)
    if db.query(InventoryProduct.id).filter_by(organization_id=m.organization_id, sku=sku).first():
        raise HTTPException(409, "Medicine SKU already exists")
    price = _decimal(payload.get("sale_price", "0"), "sale_price", places=2)
    if price<0:raise HTTPException(422,"Medicine sale price cannot be negative")
    product = InventoryProduct(organization_id=m.organization_id, sku=sku,
        name=f"{generic} {payload.get('strength','')}".strip(), description=str(payload.get("brand_name",""))[:500],
        unit=unit, sale_price=price, cost_price=Decimal("0"), tax_rate=Decimal("0"),
        is_active=True, created_by=u.id)
    db.add(product); db.flush()
    data = {"inventory_product_id": product.id, "sku": sku, "generic_name": generic,
        "brand_name": str(payload.get("brand_name","")).strip()[:180],
        "active_ingredient": str(payload.get("active_ingredient",generic)).strip()[:180],
        "strength": str(payload.get("strength","")).strip()[:80], "dosage_form": form,
        "route": route, "unit": unit, "sale_price": str(price),
        "is_controlled": bool(payload.get("is_controlled", False))}
    row = _create(db, m, u, "pharmacy_medicine", data,
        status="active", external_key=sku)
    _audit_action(db,m,u,"pharmacy.medicine.created","pharmacy_medicine",row.id,sku)
    db.commit()
    return {"id": row.id, **data, "status": row.status}


@router.get("/pharmacy/medicines")
def list_pharmacy_medicines(m=Depends(active_membership), u: User=Depends(current_user),
    db: Session=Depends(get_db), limit: int=Query(200, ge=1, le=1000)):
    _need_any(db,m,u,"pharmacy.manage")
    rows = _resource_list(db,m,"pharmacy_medicine",status="active",limit=limit)
    return [{"id":x.id,**_payload(x)} for x in rows]


@router.post("/pharmacy/medicines/{medicine_id}/batches", status_code=201)
def receive_pharmacy_batch(medicine_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    medicine, med = _medicine(db,m,medicine_id)
    branch_id = _required_text(payload,"branch_id",36)
    _need(db,m,u,"pharmacy.manage",branch_id)
    branch=db.query(Branch).filter_by(id=branch_id,organization_id=m.organization_id,is_active=True).first()
    if not branch: raise HTTPException(404,"Active branch not found")
    batch_no=_required_text(payload,"batch_number",80).upper()
    expiry=_date(payload.get("expiry_date"),"expiry_date")
    if expiry<=date.today(): raise HTTPException(422,"Expired or same-day expiry stock cannot be received")
    qty=_decimal(payload.get("received_quantity"),"received_quantity",True)
    cost=_decimal(payload.get("unit_cost"),"unit_cost",places=2)
    price=_decimal(payload.get("selling_price"),"selling_price",places=2)
    if cost<0 or price<0:raise HTTPException(422,"Batch cost and selling price cannot be negative")
    client=_required_text(payload,"client_batch_id",100)
    existing=_resource_list(db,m,"pharmacy_batch",branch_id=branch_id,limit=1000)
    for x in existing:
        d=_payload(x)
        if d.get("client_batch_id")==client:
            if d.get("medicine_id")==medicine_id and d.get("batch_number")==batch_no and d.get("received_quantity")==str(qty):
                return {"id":x.id,"status":"already_recorded","remaining_quantity":d["remaining_quantity"]}
            raise HTTPException(409,"Batch client ID reused with different data")
        if d.get("medicine_id")==medicine_id and d.get("batch_number")==batch_no:
            raise HTTPException(409,"Batch number already exists for this medicine and branch")
    data={"medicine_id":medicine_id,"inventory_product_id":med["inventory_product_id"],
        "branch_id":branch_id,"batch_number":batch_no,"client_batch_id":client,
        "expiry_date":expiry.isoformat(),"received_quantity":str(qty),
        "remaining_quantity":str(qty),"unit_cost":str(cost),"selling_price":str(price),
        "status":"active","received_by":u.id,"received_at":NOW().isoformat()}
    row=_create(db,m,u,"pharmacy_batch",data,branch_id=branch_id,parent_id=medicine.id,
        external_key=f"{medicine_id}:{branch_id}:{batch_no}",
        idempotency_key=f"batch:{hashlib.sha256(client.encode()).hexdigest()[:64]}")
    _movement(db,m,u,med["inventory_product_id"],branch_id,qty,"receipt",
        f"pharmacy-batch:{row.id}",f"pharm-batch:{hashlib.sha256(client.encode()).hexdigest()[:40]}")
    if med.get("is_controlled"):
        _controlled_event(db,m,u,medicine_id,row.id,None,"received",qty,"Controlled batch receipt",branch_id=branch_id)
    _audit_action(db,m,u,"pharmacy.batch.received","pharmacy_batch",row.id,f"qty:{qty};expiry:{expiry}")
    db.commit()
    return {"id":row.id,"status":"received","remaining_quantity":str(qty)}


@router.get("/pharmacy/batches")
def list_pharmacy_batches(medicine_id:int|None=None,branch_id:str|None=None,status:str|None=None,
    m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db),
    limit:int=Query(200,ge=1,le=1000)):
    _need(db,m,u,"pharmacy.manage",branch_id)
    rows=_resource_list(db,m,"pharmacy_batch",branch_id=branch_id,limit=limit)
    result=[]
    for row in rows:
        data=_payload(row)
        if medicine_id and data.get("medicine_id")!=medicine_id: continue
        expired=_date(data["expiry_date"],"expiry_date")<date.today()
        state="expired" if expired else row.status
        if status and state!=status: continue
        medrow=_get(db,m,data["medicine_id"],"pharmacy_medicine")
        med=_payload(medrow)
        result.append({"id":row.id,"medicine_id":medrow.id,"sku":med["sku"],
            "medicine_name":med["generic_name"],"branch_id":row.branch_id,
            "batch_number":data["batch_number"],"expiry_date":data["expiry_date"],
            "received_quantity":data["received_quantity"],"remaining_quantity":data["remaining_quantity"],
            "status":state,"unit_cost":data["unit_cost"],"selling_price":data["selling_price"]})
    return result


def _remove_batch_stock(db,m,u,row,data,reason,event_type):
    qty=Decimal(data.get("remaining_quantity","0"))
    if qty>0:
        _movement(db,m,u,data["inventory_product_id"],row.branch_id,-qty,"issue",
            f"pharmacy-{event_type}:{row.id}",f"pharm-{event_type}:{row.id}")
    data["remaining_quantity"]="0";data["status"]=event_type
    _update(row,data,u,status=event_type)
    medrow=_get(db,m,data["medicine_id"],"pharmacy_medicine")
    med=_payload(medrow)
    if med.get("is_controlled"):
        _controlled_event(db,m,u,medrow.id,row.id,None,event_type,qty,reason,branch_id=row.branch_id)
    return qty


@router.post("/pharmacy/batches/{batch_id}/quarantine")
def quarantine_pharmacy_batch(batch_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    row,data=_batch(db,m,batch_id,lock=True);_need(db,m,u,"pharmacy.manage",row.branch_id)
    if row.status!="active":raise HTTPException(409,"Only active batches can be quarantined")
    reason=_required_text(payload,"reason",500)
    qty=_remove_batch_stock(db,m,u,row,data,reason,"quarantined")
    _audit_action(db,m,u,"pharmacy.batch.quarantined","pharmacy_batch",row.id,reason)
    db.commit()
    return {"id":row.id,"status":row.status,"quantity_removed":str(qty)}


@router.post("/pharmacy/batches/{batch_id}/recall")
def recall_pharmacy_batch(batch_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    row,data=_batch(db,m,batch_id,lock=True);_need(db,m,u,"pharmacy.manage",row.branch_id)
    if row.status not in {"active","quarantined"}:raise HTTPException(409,"Batch cannot be recalled")
    reason=_required_text(payload,"reason",500)
    qty=Decimal(data.get("remaining_quantity","0"))
    if row.status=="active":
        qty=_remove_batch_stock(db,m,u,row,data,reason,"recalled")
    else:
        data["status"]="recalled";_update(row,data,u,status="recalled")
    _create(db,m,u,"pharmacy_recall",{"batch_id":row.id,"reason":reason,
        "quantity_removed":str(qty)},branch_id=row.branch_id,parent_id=row.id,status="completed")
    _audit_action(db,m,u,"pharmacy.batch.recalled","pharmacy_batch",row.id,reason)
    db.commit()
    return {"id":row.id,"status":"recalled","quantity_removed":str(qty)}


@router.post("/pharmacy/batches/expire")
def expire_pharmacy_batches(m=Depends(active_membership),u:User=Depends(current_user),
    db:Session=Depends(get_db),as_of:date|None=None):
    cutoff=as_of or date.today()
    rows=_resource_list(db,m,"pharmacy_batch",limit=1000)
    count=0;total=Decimal("0")
    for row in rows:
        try:
            _need(db,m,u,"pharmacy.manage",row.branch_id)
        except HTTPException as exc:
            if exc.status_code==403:continue
            raise
        row,data=_batch(db,m,row.id,lock=True)
        if row.status=="active" and _date(data["expiry_date"],"expiry_date")<cutoff:
            qty=_remove_batch_stock(db,m,u,row,data,"Expired batch removed from saleable inventory","expired")
            count+=1;total+=qty
    _audit_action(db,m,u,"pharmacy.expiry.sweep","pharmacy_batch","expiry-sweep",
        f"as_of:{cutoff};count:{count};qty:{total}")
    db.commit()
    return {"as_of":cutoff.isoformat(),"expired_count":count,"quantity_removed":str(total)}


@router.post("/pharmacy/batches/{batch_id}/adjust")
def adjust_pharmacy_batch(batch_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    row,data=_batch(db,m,batch_id,lock=True);_need(db,m,u,"pharmacy.manage",row.branch_id)
    if row.status!="active" or _date(data["expiry_date"],"expiry_date")<date.today():
        raise HTTPException(409,"Only active unexpired batches can be adjusted")
    roles=_need(db,m,u,"pharmacy.manage",row.branch_id)
    verifier_id=int(payload.get("verifier_id",0));reason=_required_text(payload,"reason",500)
    if verifier_id==u.id:raise HTTPException(403,"A second verifier is required")
    from app.api.healthcare_hospital import _roles
    verifier=db.query(User).filter_by(id=verifier_id,is_active=True).first()
    if not verifier or not _roles(db,m,verifier,row.branch_id).intersection(PHARMACY_ROLES):
        raise HTTPException(403,"A second pharmacist or healthcare administrator must verify")
    delta=_decimal(payload.get("quantity_delta"),"quantity_delta",places=3)
    if delta==0:raise HTTPException(422,"Adjustment cannot be zero")
    key=_required_text(payload,"idempotency_key",100)
    prior=db.query(HealthcareResource).filter_by(organization_id=m.organization_id,
        resource_type="pharmacy_stock_adjustment",idempotency_key=key).first()
    if prior:
        prior_data=_payload(prior)
        if prior.parent_id!=row.id or Decimal(prior_data["delta"])!=delta or prior_data["reason"]!=reason:
            raise HTTPException(409,"Stock adjustment idempotency key conflicts with a previous request")
        return {"batch_id":row.id,"remaining_quantity":prior_data["balance_after"],"status":"already_recorded"}
    new_qty=Decimal(data["remaining_quantity"])+delta
    if new_qty<0:raise HTTPException(409,"Adjustment would make batch stock negative")
    data["remaining_quantity"]=str(new_qty);_update(row,data,u)
    movement_key=f"pharm-adjust:{hashlib.sha256(key.encode()).hexdigest()[:48]}"
    _movement(db,m,u,data["inventory_product_id"],row.branch_id,delta,"adjustment",
        f"pharmacy-adjust:{row.id}",movement_key)
    medrow=_get(db,m,data["medicine_id"],"pharmacy_medicine")
    if _payload(medrow).get("is_controlled"):
        _controlled_event(db,m,u,medrow.id,row.id,None,"stock_adjustment",delta,reason,verifier_id,branch_id=row.branch_id)
    _create(db,m,u,"pharmacy_stock_adjustment",{"batch_id":row.id,"delta":str(delta),
        "reason":reason,"verifier_id":verifier_id,"balance_after":str(new_qty)},
        branch_id=row.branch_id,parent_id=row.id,status="posted",idempotency_key=key)
    _audit_action(db,m,u,"pharmacy.batch.adjusted","pharmacy_batch",row.id,reason)
    db.commit()
    return {"batch_id":row.id,"remaining_quantity":str(new_qty)}


# ---------------- Prescriptions, safety and dispensing ----------------

@router.post("/pharmacy/allergies",status_code=201)
def record_pharmacy_allergy(payload:dict,m=Depends(active_membership),u:User=Depends(current_user),
    db:Session=Depends(get_db)):
    patient_id=int(payload.get("patient_id",0))
    patient,emergency,roles=_patient_access(db,m,u,patient_id,"clinical.read",write=False)
    _need(db,m,u,"pharmacy.manage",patient.branch_id)
    allergen=_required_text(payload,"allergen",180)
    severity=str(payload.get("severity","unknown"))
    if severity not in {"unknown","mild","moderate","severe"}:raise HTTPException(422,"Invalid allergy severity")
    data={"allergen":allergen,"reaction":str(payload.get("reaction",""))[:500],
        "severity":severity,"status":"active","recorded_by":u.id,"recorded_at":NOW().isoformat()}
    row=_create(db,m,u,"pharmacy_allergy",data,patient.branch_id,patient.id,status="active")
    _patient_event(db,m,u,patient,"pharmacy.allergy.recorded",{"allergy_id":row.id,"allergen":allergen},row.id)
    db.commit()
    return {"id":row.id,"patient_id":patient.id,"allergen":allergen,"severity":severity}


@router.get("/pharmacy/allergies/{patient_id}")
def list_pharmacy_allergies(patient_id:int,m=Depends(active_membership),u:User=Depends(current_user),
    db:Session=Depends(get_db)):
    patient,_,_=_patient_read(db,m,u,patient_id)
    _need(db,m,u,"pharmacy.manage",patient.branch_id)
    rows=_resource_list(db,m,"pharmacy_allergy",patient_id=patient.id,limit=1000)
    return [{"id":x.id,**_payload(x)} for x in rows]


@router.post("/pharmacy/safety-rules",status_code=201)
def create_pharmacy_safety_rule(payload:dict,m=Depends(active_membership),u:User=Depends(current_user),
    db:Session=Depends(get_db)):
    _need_any(db,m,u,"pharmacy.manage")
    a_id=int(payload.get("medicine_a_id",0));b_id=int(payload["medicine_b_id"]) if payload.get("medicine_b_id") else None
    _medicine(db,m,a_id)
    if b_id:_medicine(db,m,b_id)
    rule_type=str(payload.get("rule_type",""))
    severity=str(payload.get("severity","warning"))
    if rule_type not in {"interaction","allergy"} or severity not in {"warning","block"}:
        raise HTTPException(422,"Invalid safety rule type or severity")
    if rule_type=="interaction" and (not b_id or a_id==b_id):
        raise HTTPException(422,"Interaction rules require two different medicines")
    if rule_type=="allergy" and b_id:
        raise HTTPException(422,"Allergy rules apply to one medicine")
    data={"medicine_a_id":a_id,"medicine_b_id":b_id,"rule_type":rule_type,
        "severity":severity,"description":_required_text(payload,"description",500),"is_active":True}
    row=_create(db,m,u,"pharmacy_safety_rule",data,status="active",
        idempotency_key=payload.get("idempotency_key"))
    _audit_action(db,m,u,"pharmacy.safety_rule.created","pharmacy_safety_rule",row.id)
    db.commit()
    return {"id":row.id,"rule_type":rule_type,"severity":severity}


@router.post("/pharmacy/prescriptions",status_code=201)
def create_pharmacy_prescription(payload:dict,m=Depends(active_membership),u:User=Depends(current_user),
    db:Session=Depends(get_db)):
    encounter_id=int(payload.get("encounter_id",0))
    encounter=db.query(HealthcareEncounter).filter_by(
        id=encounter_id,organization_id=m.organization_id,status="open").first()
    if not encounter or encounter.clinician_user_id!=u.id:
        raise HTTPException(403,"Prescription requires an open encounter assigned to the current prescriber")
    patient,emergency,_=_patient_write(db,m,u,encounter.patient_id)
    _need(db,m,u,"orders.manage",patient.branch_id)
    prescription_no=_required_text(payload,"prescription_number",80).upper()
    valid_until=_date(payload.get("valid_until"),"valid_until")
    if valid_until<date.today():raise HTTPException(422,"Prescription validity cannot be in the past")
    lines=payload.get("lines")
    if not isinstance(lines,list) or not 1<=len(lines)<=30:raise HTTPException(422,"Prescription requires 1 to 30 lines")
    medicine_ids=[]
    normalized=[]
    for item in lines:
        mid=int(item.get("medicine_id",0));_,med=_medicine(db,m,mid);medicine_ids.append(mid)
        quantity=_decimal(item.get("quantity"),"quantity",True)
        duration=int(item.get("duration_days",0));refills=int(item.get("refills_allowed",0))
        if not 1<=duration<=365 or not 0<=refills<=12:raise HTTPException(422,"Invalid duration or refill allowance")
        normalized.append({"medicine_id":mid,"dose":_required_text(item,"dose",120),
            "frequency":_required_text(item,"frequency",120),"duration_days":duration,
            "quantity_prescribed":str(quantity),"quantity_dispensed":"0",
            "refills_allowed":refills,"refills_used":0,"status":"pending"})
    if len(set(medicine_ids))!=len(medicine_ids):raise HTTPException(422,"Duplicate medicines in prescription")
    warnings=_check_drug_safety(db,m,patient.id,medicine_ids,
        _active_patient_medicine_ids(db,m,patient.id))
    data={"prescription_number":prescription_no,"patient_id":patient.id,
        "encounter_id":encounter.id,"prescriber_id":u.id,"valid_until":valid_until.isoformat(),
        "lines":normalized,"status":"active","issued_at":NOW().isoformat(),"safety_warnings":warnings}
    row=_create(db,m,u,"pharmacy_prescription",data,patient.branch_id,patient.id,
        status="active",external_key=prescription_no,
        idempotency_key=str(payload.get("idempotency_key") or f"rx:{prescription_no}"))
    _patient_event(db,m,u,patient,"pharmacy.prescription.issued",
        {"prescription_id":row.id,"encounter_id":encounter.id,"line_count":len(normalized)},row.id)
    db.commit()
    return {"id":row.id,"prescription_number":prescription_no,"status":row.status,
        "safety_warnings":warnings,"lines":normalized}


@router.get("/pharmacy/prescriptions")
def list_pharmacy_prescriptions(patient_id:int|None=None,status:str|None=None,branch_id:str|None=None,
    m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db),
    limit:int=Query(100,ge=1,le=500)):
    if patient_id:
        patient,_,_=_patient_read(db,m,u,patient_id)
        branch_id=branch_id or patient.branch_id
    _need(db,m,u,"pharmacy.manage",branch_id)
    rows=_resource_list(db,m,"pharmacy_prescription",branch_id=branch_id,
        patient_id=patient_id,status=status,limit=limit)
    return [{"id":x.id,"patient_id":x.patient_id,"status":x.status,
        "prescription_number":_payload(x).get("prescription_number"),
        "valid_until":_payload(x).get("valid_until")} for x in rows]


@router.get("/pharmacy/prescriptions/{prescription_id}")
def get_pharmacy_prescription(prescription_id:int,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    row=_get(db,m,prescription_id,"pharmacy_prescription")
    _need(db,m,u,"pharmacy.manage",row.branch_id)
    _patient_read(db,m,u,row.patient_id)
    return _view(row)


@router.post("/pharmacy/prescriptions/{prescription_id}/dispense",status_code=201)
def dispense_pharmacy_prescription(prescription_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    rx=_get(db,m,prescription_id,"pharmacy_prescription",lock=True)
    _need(db,m,u,"pharmacy.manage",rx.branch_id)
    patient,_,_=_patient_read(db,m,u,rx.patient_id)
    data=_payload(rx)
    if rx.status not in {"active","partially_dispensed"} or _date(data["valid_until"],"valid_until")<date.today():
        raise HTTPException(409,"Prescription is no longer valid")
    line_index=int(payload.get("line_index",-1))
    if line_index<0 or line_index>=len(data["lines"]):raise HTTPException(404,"Prescription line not found")
    line=data["lines"][line_index]
    verifier_id=int(payload.get("verifier_id",0))
    if verifier_id == u.id:
        raise HTTPException(403,"The dispensing pharmacist cannot verify their own dispense")
    _verifier(db,m,verifier_id,rx.branch_id)
    qty=_decimal(payload.get("quantity"),"quantity",True)
    total_authorized=Decimal(line["quantity_prescribed"])*Decimal(1+int(line["refills_allowed"]))
    if Decimal(line["quantity_dispensed"])+qty>total_authorized:
        raise HTTPException(422,"Dispense exceeds prescribed quantity and authorized refills")
    key=_required_text(payload,"idempotency_key",100)
    prior=db.query(HealthcareResource).filter_by(
        organization_id=m.organization_id,resource_type="pharmacy_dispense",idempotency_key=key).first()
    if prior:
        prior_data=_payload(prior)
        if (prior.parent_id!=rx.id or Decimal(prior_data["quantity"])!=qty
            or int(prior_data["line_index"])!=line_index
            or int(prior_data.get("requested_batch_id") or 0)!=int(payload.get("batch_id") or 0)):
            raise HTTPException(409,"Dispense idempotency key conflicts with another request")
        return {"id":prior.id,"status":"already_recorded","quantity":str(qty)}
    medicine_id=int(line["medicine_id"]);medrow,med=_medicine(db,m,medicine_id)
    safety_warnings=_check_drug_safety(db,m,patient.id,[medicine_id],
        _active_patient_medicine_ids(db,m,patient.id))
    requested_batch=int(payload["batch_id"]) if payload.get("batch_id") else None
    batches=_resource_list(db,m,"pharmacy_batch",branch_id=rx.branch_id,limit=1000)
    candidates=[]
    for b in batches:
        bd=_payload(b)
        if bd.get("medicine_id")!=medicine_id or b.status!="active":continue
        if _date(bd["expiry_date"],"expiry_date")<date.today():continue
        if requested_batch and b.id!=requested_batch:continue
        if Decimal(bd["remaining_quantity"])>0:candidates.append((b,bd))
    candidates.sort(key=lambda x:(_date(x[1]["expiry_date"],"expiry_date"),x[0].id))
    remaining=qty;allocations=[]
    for candidate,_ in candidates:
        batch,bd=_batch(db,m,candidate.id,lock=True)
        if batch.status!="active" or bd.get("medicine_id")!=medicine_id:
            continue
        if _date(bd["expiry_date"],"expiry_date")<date.today():
            continue
        available=Decimal(bd["remaining_quantity"])
        take=min(remaining,available)
        if take<=0:continue
        bd["remaining_quantity"]=str(Decimal(bd["remaining_quantity"])-take)
        _update(batch,bd,u)
        allocations.append({"batch_id":batch.id,"quantity":str(take),
            "unit_price":bd["selling_price"],"batch_number":bd["batch_number"]})
        remaining-=take
        if remaining==0:break
    if remaining>0:raise HTTPException(409,"Insufficient unexpired stock in eligible batches")
    previous_dispensed=Decimal(line["quantity_dispensed"])
    refill_number=max(0,int(previous_dispensed//Decimal(line["quantity_prescribed"])))
    line["quantity_dispensed"]=str(previous_dispensed+qty)
    line["refills_used"]=min(int(line["refills_allowed"]),max(0,int(Decimal(line["quantity_dispensed"])//Decimal(line["quantity_prescribed"]))-1))
    line["status"]="dispensed" if Decimal(line["quantity_dispensed"])>=total_authorized else "partially_dispensed"
    data["lines"][line_index]=line
    data["status"]="dispensed" if all(x["status"]=="dispensed" for x in data["lines"]) else "partially_dispensed"
    _update(rx,data,u,status=data["status"])
    amount=sum((Decimal(a["quantity"])*Decimal(a["unit_price"]) for a in allocations),Decimal("0")).quantize(Decimal("0.01"))
    disp=_create(db,m,u,"pharmacy_dispense",{"prescription_id":rx.id,"line_index":line_index,
        "patient_id":rx.patient_id,"quantity":str(qty),"allocations":allocations,
        "requested_batch_id":requested_batch,"refill_number":refill_number,
        "pharmacist_id":u.id,"verifier_id":verifier_id,"dispensed_at":NOW().isoformat()},
        rx.branch_id,rx.patient_id,parent_id=rx.id,status="dispensed",
        idempotency_key=key,amount=amount,currency="KES")
    for allocation in allocations:
        _movement(db,m,u,med["inventory_product_id"],rx.branch_id,
            -Decimal(allocation["quantity"]),"issue",f"pharmacy-dispense:{disp.id}",
            f"pharm-dispense:{disp.id}:{allocation['batch_id']}")
        if med.get("is_controlled"):
            _controlled_event(db,m,u,medicine_id,allocation["batch_id"],rx.patient_id,
                "dispensed",Decimal(allocation["quantity"]),"Prescription dispense",verifier_id,disp.id,rx.branch_id)
    invoice=_create(db,m,u,"pharmacy_invoice",{"patient_id":rx.patient_id,
        "source_type":"pharmacy_dispense","source_id":disp.id,"amount":str(amount),
        "currency":"KES","status":"unpaid"},rx.branch_id,rx.patient_id,parent_id=disp.id,
        status="unpaid",amount=amount,currency="KES")
    _patient_event(db,m,u,patient,"pharmacy.dispense.completed",
        {"prescription_id":rx.id,"dispense_id":disp.id,"quantity":str(qty),"invoice_id":invoice.id},
        disp.id,key)
    db.commit()
    return {"id":disp.id,"status":"dispensed","quantity":str(qty),
        "allocations":allocations,"amount":str(amount),"invoice_id":invoice.id,
        "safety_warnings":safety_warnings,"prescription_status":rx.status}


@router.post("/pharmacy/prescriptions/{prescription_id}/refill",status_code=201)
def refill_pharmacy_prescription(prescription_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    rx=_get(db,m,prescription_id,"pharmacy_prescription",lock=True)
    _need(db,m,u,"pharmacy.manage",rx.branch_id)
    data=_payload(rx);idx=int(payload.get("line_index",-1))
    if idx<0 or idx>=len(data["lines"]):raise HTTPException(404,"Prescription line not found")
    line=data["lines"][idx]
    if rx.status not in {"active","partially_dispensed"} or _date(data["valid_until"],"valid_until")<date.today():
        raise HTTPException(409,"Prescription is not eligible for refill")
    prescribed=Decimal(line["quantity_prescribed"]);dispensed=Decimal(line["quantity_dispensed"])
    used=int(line.get("refills_used",0));allowed=int(line.get("refills_allowed",0))
    if used>=allowed or dispensed < prescribed*(used+1):
        raise HTTPException(409,"The previous authorized quantity must be fully dispensed before the next refill")
    quantity=_decimal(payload.get("quantity"),"quantity",True)
    if quantity>prescribed:
        raise HTTPException(422,"A refill cannot exceed the originally prescribed quantity")
    refill_payload={**payload,"line_index":idx,"quantity":str(quantity),"is_refill":True}
    return dispense_pharmacy_prescription(prescription_id,refill_payload,m,u,db)


@router.post("/pharmacy/prescriptions/{prescription_id}/cancel")
def cancel_pharmacy_prescription(prescription_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    rx=_get(db,m,prescription_id,"pharmacy_prescription",lock=True)
    roles=_need(db,m,u,"orders.manage",rx.branch_id)
    data=_payload(rx)
    if rx.status not in {"active","partially_dispensed"}:
        raise HTTPException(409,"Prescription cannot be cancelled from its current state")
    if u.id!=data.get("prescriber_id") and "healthcare_admin" not in roles:
        raise HTTPException(403,"Only the prescriber or healthcare administrator may cancel this prescription")
    reason=_required_text(payload,"reason",500)
    data["status"]="cancelled";data["cancelled_by"]=u.id
    data["cancelled_at"]=NOW().isoformat();data["cancellation_reason"]=reason
    _update(rx,data,u,status="cancelled")
    patient=_patient(db,rx.patient_id,m)
    _patient_event(db,m,u,patient,"pharmacy.prescription.cancelled",
        {"prescription_id":rx.id,"reason":reason},rx.id)
    db.commit()
    return {"prescription_id":rx.id,"status":rx.status}


@router.post("/pharmacy/dispenses/{dispense_id}/return",status_code=201)
def return_pharmacy_dispense(dispense_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    disp=_get(db,m,dispense_id,"pharmacy_dispense",lock=True)
    _need(db,m,u,"pharmacy.manage",disp.branch_id)
    data=_payload(disp);patient,_,_=_patient_read(db,m,u,disp.patient_id)
    qty=_decimal(payload.get("quantity"),"quantity",True)
    reason=_required_text(payload,"reason",500)
    return_key=_required_text(payload,"idempotency_key",100)
    prior=db.query(HealthcareResource).filter_by(organization_id=m.organization_id,
        resource_type="pharmacy_return",idempotency_key=return_key).first()
    if prior:
        prior_data=_payload(prior)
        if prior.parent_id!=disp.id or Decimal(prior_data["quantity"])!=qty or prior_data["reason"]!=reason:
            raise HTTPException(409,"Return idempotency key conflicts with a previous request")
        return {"return_id":prior.id,"status":"already_recorded"}
    previous=_resource_list(db,m,"pharmacy_return",patient_id=disp.patient_id,limit=1000)
    returned=sum((Decimal(_payload(x)["quantity"]) for x in previous if _payload(x).get("dispense_id")==disp.id),Decimal("0"))
    if returned+qty>Decimal(data["quantity"]):raise HTTPException(422,"Return exceeds dispensed quantity")
    return_allocations=[];remaining=qty
    for allocation in data["allocations"]:
        prior_qty=sum((Decimal(_payload(x).get("quantity","0")) for x in previous
            if _payload(x).get("dispense_id")==disp.id
            for a in _payload(x).get("allocations",[]) if int(a["batch_id"])==int(allocation["batch_id"])),Decimal("0"))
        available=max(Decimal("0"),Decimal(allocation["quantity"])-prior_qty)
        take=min(remaining,available)
        if take>0:
            return_allocations.append({"batch_id":int(allocation["batch_id"]),"quantity":str(take)})
            remaining-=take
        if remaining==0:break
    if remaining>0:raise HTTPException(409,"Unable to trace returned quantity to original dispensed batches")
    row=_create(db,m,u,"pharmacy_return",{"dispense_id":disp.id,"quantity":str(qty),
        "allocations":return_allocations,"reason":reason,"stock_disposition":"quarantine_pending",
        "recorded_by":u.id,"recorded_at":NOW().isoformat()},
        disp.branch_id,disp.patient_id,parent_id=disp.id,status="quarantine_pending",
        idempotency_key=return_key)
    _patient_event(db,m,u,patient,"pharmacy.dispense.returned",
        {"dispense_id":disp.id,"return_id":row.id,"quantity":str(qty),"reason":reason},row.id)
    db.commit()
    return {"return_id":row.id,"status":"quarantine_pending",
        "note":"Returned product is not restored to saleable inventory."}


@router.post("/pharmacy/returns/{return_id}/disposition")
def decide_pharmacy_return(return_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    row=_get(db,m,return_id,"pharmacy_return",lock=True)
    _need(db,m,u,"pharmacy.manage",row.branch_id)
    if row.status!="quarantine_pending":
        raise HTTPException(409,"Return has already received a disposition")
    data=_payload(row);decision=str(payload.get("decision",""))
    if decision not in {"quarantine","discard","restock"}:
        raise HTTPException(422,"Disposition must be quarantine, discard or restock")
    reason=_required_text(payload,"reason",500)
    verifier_id=int(payload.get("verifier_id",0))
    if decision=="restock":
        if verifier_id==u.id:
            raise HTTPException(403,"A second pharmacist must verify returned stock")
        _verifier(db,m,verifier_id,row.branch_id)
        if payload.get("sealed") is not True:
            raise HTTPException(422,"Only sealed, saleable returned medicine may be restocked")
        for allocation in data["allocations"]:
            batch,bd=_batch(db,m,int(allocation["batch_id"]),lock=True)
            if batch.status!="active" or _date(bd["expiry_date"],"expiry_date")<date.today():
                raise HTTPException(409,"Returned stock cannot be restored to an expired or recalled batch")
            qty=Decimal(allocation["quantity"])
            bd["remaining_quantity"]=str(Decimal(bd["remaining_quantity"])+qty)
            _update(batch,bd,u)
            medrow,med=_medicine(db,m,int(bd["medicine_id"]))
            _movement(db,m,u,med["inventory_product_id"],row.branch_id,qty,"receipt",
                f"pharmacy-return:{row.id}",f"pharm-return:{row.id}:{batch.id}")
            if med.get("is_controlled"):
                _controlled_event(db,m,u,medrow.id,batch.id,row.patient_id,"returned_to_stock",
                    qty,reason,verifier_id,row.id,row.branch_id)
    data["stock_disposition"]=decision;data["disposition_reason"]=reason
    data["disposition_by"]=u.id;data["disposition_at"]=NOW().isoformat()
    data["verifier_id"]=verifier_id if decision=="restock" else None
    _update(row,data,u,status=decision)
    patient=_patient(db,row.patient_id,m)
    _patient_event(db,m,u,patient,"pharmacy.return.disposition",
        {"return_id":row.id,"decision":decision,"reason":reason},row.id)
    db.commit()
    return {"return_id":row.id,"status":row.status,"restocked":decision=="restock"}


@router.post("/pharmacy/dispenses/{dispense_id}/reverse")
def reverse_pharmacy_dispense(dispense_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    disp=_get(db,m,dispense_id,"pharmacy_dispense",lock=True)
    _need(db,m,u,"pharmacy.manage",disp.branch_id)
    if disp.status!="dispensed":raise HTTPException(409,"Dispense is not reversible")
    data=_payload(disp);patient,_,_=_patient_read(db,m,u,disp.patient_id)
    prior_returns=_resource_list(db,m,"pharmacy_return",patient_id=disp.patient_id,limit=1000)
    if any(_payload(x).get("dispense_id")==disp.id for x in prior_returns):
        raise HTTPException(409,"A dispense with a recorded return cannot be reversed; disposition the return instead")
    verifier_id=int(payload.get("verifier_id",0))
    if verifier_id==u.id:raise HTTPException(403,"A second pharmacist must verify the reversal")
    _verifier(db,m,verifier_id,disp.branch_id)
    reason=_required_text(payload,"reason",500)
    restock=_decimal(payload.get("restock_quantity","0"),"restock_quantity",places=3)
    if restock<0 or restock>Decimal(data["quantity"]):raise HTTPException(422,"Invalid restock quantity")
    allocations=data["allocations"]
    total=sum((Decimal(a["quantity"]) for a in allocations),Decimal("0"))
    remaining_restock=restock
    for a in allocations:
        batch,bd=_batch(db,m,int(a["batch_id"]),lock=True)
        if batch.status!="active" or _date(bd["expiry_date"],"expiry_date")<date.today():
            if remaining_restock>0:raise HTTPException(409,"Expired or recalled stock cannot be restocked")
            continue
        take=min(remaining_restock,Decimal(a["quantity"]))
        if take>0:
            bd["remaining_quantity"]=str(Decimal(bd["remaining_quantity"])+take)
            _update(batch,bd,u)
            medrow,med=_medicine(db,m,int(bd["medicine_id"]))
            _movement(db,m,u,med["inventory_product_id"],batch.branch_id,take,"receipt",
                f"pharmacy-dispense-reversal:{disp.id}",f"pharm-reversal:{disp.id}:{batch.id}")
            remaining_restock-=take
    if remaining_restock>0:raise HTTPException(409,"Unable to allocate requested restock quantity")
    disp.status="reversed";disp.updated_by=u.id;disp.updated_at=NOW()
    rx=_get(db,m,int(data["prescription_id"]),"pharmacy_prescription",lock=True)
    rxd=_payload(rx);idx=int(data["line_index"]);line=rxd["lines"][idx]
    line["quantity_dispensed"]=str(max(Decimal("0"),Decimal(line["quantity_dispensed"])-total))
    line["refills_used"]=min(int(line.get("refills_allowed",0)),max(0,int(Decimal(line["quantity_dispensed"])//Decimal(line["quantity_prescribed"]))-1))
    authorized=Decimal(line["quantity_prescribed"])*(1+int(line.get("refills_allowed",0)))
    line["status"]="pending" if Decimal(line["quantity_dispensed"])==0 else "dispensed" if Decimal(line["quantity_dispensed"])>=authorized else "partially_dispensed"
    rxd["lines"][idx]=line
    if rxd.get("status")!="cancelled":
        rxd["status"]="active" if all(x["status"]=="pending" for x in rxd["lines"]) else (
            "dispensed" if all(x["status"]=="dispensed" for x in rxd["lines"]) else "partially_dispensed")
    _update(rx,rxd,u,status=rxd["status"])
    invoice_rows=_resource_list(db,m,"pharmacy_invoice",patient_id=disp.patient_id,limit=1000)
    for inv in invoice_rows:
        if _payload(inv).get("source_id")==disp.id:
            inv.status="reversed";iv=_payload(inv);iv["status"]="reversed";_update(inv,iv,u,status="reversed")
    for allocation in allocations:
        medrow,med=_medicine(db,m,int(_payload(_batch(db,m,int(allocation["batch_id"]))[0])["medicine_id"]))
        if med.get("is_controlled"):
            _controlled_event(db,m,u,medrow.id,int(allocation["batch_id"]),disp.patient_id,
                "dispense_reversed",Decimal(allocation["quantity"]),reason,verifier_id,disp.id,disp.branch_id)
    row=_create(db,m,u,"pharmacy_controlled_event",{"event_type":"dispense_reversed",
        "dispense_id":disp.id,"quantity":str(total),"reason":reason,"verifier_id":verifier_id},
        disp.branch_id,disp.patient_id,parent_id=disp.id,status="reversed")
    _patient_event(db,m,u,patient,"pharmacy.dispense.reversed",
        {"dispense_id":disp.id,"restock_quantity":str(restock),"reason":reason},row.id)
    db.commit()
    return {"dispense_id":disp.id,"status":"reversed","restocked":str(restock)}


@router.post("/pharmacy/replenishment",status_code=201)
def request_pharmacy_replenishment(payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    medicine_id=int(payload.get("medicine_id",0));branch_id=_required_text(payload,"branch_id",36)
    _need(db,m,u,"pharmacy.manage",branch_id)
    medrow,med=_medicine(db,m,medicine_id)
    qty=_decimal(payload.get("quantity"),"quantity",True)
    supplier_id=int(payload["supplier_id"]) if payload.get("supplier_id") else None
    if supplier_id and not db.query(ProcurementSupplier).filter_by(
        id=supplier_id,organization_id=m.organization_id,is_active=True).first():
        raise HTTPException(404,"Active tenant supplier not found")
    data={"medicine_id":medicine_id,"branch_id":branch_id,"quantity":str(qty),
        "supplier_id":supplier_id,"expected_unit_cost":str(_decimal(payload.get("expected_unit_cost","0"),"expected_unit_cost",places=2)),
        "reason":str(payload.get("reason",""))[:500],"status":"pending"}
    key=_required_text(payload,"idempotency_key",120)
    row=_create(db,m,u,"pharmacy_replenishment",data,branch_id=branch_id,status="pending",idempotency_key=key)
    db.commit()
    return {"id":row.id,"status":row.status}


@router.post("/pharmacy/replenishment/{request_id}/convert")
def convert_pharmacy_replenishment(request_id:int,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    request=_get(db,m,request_id,"pharmacy_replenishment",lock=True)
    _need(db,m,u,"pharmacy.manage",request.branch_id)
    data=_payload(request)
    if request.status=="converted":return {"request_id":request.id,"status":"already_converted",
        "purchase_order_id":data.get("purchase_order_id")}
    supplier_id=data.get("supplier_id")
    if not supplier_id:raise HTTPException(422,"Supplier must be selected before conversion")
    supplier=db.query(ProcurementSupplier).filter_by(id=supplier_id,
        organization_id=m.organization_id,is_active=True).first()
    medrow,med=_medicine(db,m,int(data["medicine_id"]))
    if not supplier:raise HTTPException(404,"Active supplier not found")
    po=ProcurementPurchaseOrder(organization_id=m.organization_id,branch_id=request.branch_id,
        supplier_id=supplier.id,order_number=f"PHARM-{request.id}-{uuid.uuid4().hex[:8].upper()}",
        status="draft",currency="KES",notes=f"Pharmacy replenishment #{request.id}: {data.get('reason','')}",
        created_by=u.id)
    db.add(po);db.flush()
    db.add(ProcurementPurchaseOrderLine(organization_id=m.organization_id,
        purchase_order_id=po.id,product_id=med["inventory_product_id"],
        quantity_ordered=Decimal(data["quantity"]),quantity_received=Decimal("0"),
        unit_cost=Decimal(data["expected_unit_cost"])))
    data["purchase_order_id"]=po.id;data["converted_by"]=u.id;data["converted_at"]=NOW().isoformat()
    _update(request,data,u,status="converted")
    _audit_action(db,m,u,"pharmacy.replenishment.converted","procurement_purchase_order",po.id)
    db.commit()
    return {"request_id":request.id,"status":"converted","purchase_order_id":po.id,
        "purchase_order_number":po.order_number,"purchase_order_status":"draft"}


# ---------------- Laboratory catalogue, panels and orders ----------------

def _critical_result(line, result, requested=False):
    if requested:
        return True
    try:
        value=Decimal(str(result).strip())
    except (InvalidOperation, ValueError, TypeError):
        return False
    low=line.get("critical_low");high=line.get("critical_high")
    return ((low is not None and value<=Decimal(str(low))) or
            (high is not None and value>=Decimal(str(high))))




@router.post("/lab/tests",status_code=201)
def create_laboratory_test(payload:dict,m=Depends(active_membership),u:User=Depends(current_user),
    db:Session=Depends(get_db)):
    _need_any(db,m,u,"lab.manage")
    code=_required_text(payload,"code",40).upper()
    existing=_resource_list(db,m,"lab_test",limit=1000)
    if any(_payload(x).get("code")==code for x in existing):raise HTTPException(409,"Test code already exists")
    critical_low=_decimal(payload["critical_low"],"critical_low") if payload.get("critical_low") is not None else None
    critical_high=_decimal(payload["critical_high"],"critical_high") if payload.get("critical_high") is not None else None
    if critical_low is not None and critical_high is not None and critical_low>=critical_high:
        raise HTTPException(422,"Critical low threshold must be below critical high threshold")
    data={"code":code,"name":_required_text(payload,"name"),"specimen_type":_required_text(payload,"specimen_type",80).lower(),
        "unit":str(payload.get("unit",""))[:40],"reference_range":str(payload.get("reference_range",""))[:180],
        "critical_low":str(critical_low) if critical_low is not None else None,
        "critical_high":str(critical_high) if critical_high is not None else None,
        "turnaround_hours":int(payload.get("turnaround_hours",24)),
        "price":str(_decimal(payload.get("price","0"),"price",places=2)),"is_active":True}
    if not 1<=data["turnaround_hours"]<=720:raise HTTPException(422,"Turnaround hours must be 1 to 720")
    row=_create(db,m,u,"lab_test",data,status="active",external_key=code)
    _audit_action(db,m,u,"lab.test.created","lab_test",row.id,code);db.commit()
    return {"id":row.id,**data}


@router.put("/lab/tests/{test_id}")
def update_laboratory_test(test_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    row=_get(db,m,test_id,"lab_test",lock=True)
    _need_any(db,m,u,"lab.manage")
    data=_payload(row)
    for field,limit in (("name",180),("specimen_type",80),("unit",40),("reference_range",180)):
        if field in payload:
            data[field]=_required_text(payload,field,limit).lower() if field=="specimen_type" else _required_text(payload,field,limit)
    if "price" in payload:
        data["price"]=str(_decimal(payload["price"],"price",places=2))
    if "turnaround_hours" in payload:
        hours=int(payload["turnaround_hours"])
        if not 1<=hours<=720:raise HTTPException(422,"Turnaround hours must be 1 to 720")
        data["turnaround_hours"]=hours
    if "critical_low" in payload:
        value=payload["critical_low"]
        data["critical_low"]=str(_decimal(value,"critical_low")) if value is not None else None
    if "critical_high" in payload:
        value=payload["critical_high"]
        data["critical_high"]=str(_decimal(value,"critical_high")) if value is not None else None
    low=data.get("critical_low");high=data.get("critical_high")
    if low is not None and high is not None and Decimal(low)>=Decimal(high):
        raise HTTPException(422,"Critical low threshold must be below critical high threshold")
    _update(row,data,u)
    _audit_action(db,m,u,"lab.test.updated","lab_test",row.id)
    db.commit()
    return {"id":row.id,**data,"status":row.status}


@router.post("/lab/tests/{test_id}/deactivate")
def deactivate_laboratory_test(test_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    row=_get(db,m,test_id,"lab_test",lock=True)
    _need_any(db,m,u,"lab.manage")
    if row.status!="active":raise HTTPException(409,"Test is already inactive")
    data=_payload(row);data["is_active"]=False
    data["deactivated_at"]=NOW().isoformat();data["deactivated_by"]=u.id
    data["deactivation_reason"]=_required_text(payload,"reason",500)
    _update(row,data,u,status="inactive")
    _audit_action(db,m,u,"lab.test.deactivated","lab_test",row.id,data["deactivation_reason"])
    db.commit()
    return {"id":row.id,"status":row.status}


@router.get("/lab/tests")
def list_laboratory_tests(m=Depends(active_membership),u:User=Depends(current_user),
    db:Session=Depends(get_db),limit:int=Query(500,ge=1,le=1000)):
    _need_any(db,m,u,"lab.manage")
    rows=_resource_list(db,m,"lab_test",status="active",limit=limit)
    return [{"id":x.id,**_payload(x)} for x in rows]


@router.post("/lab/panels",status_code=201)
def create_laboratory_panel(payload:dict,m=Depends(active_membership),u:User=Depends(current_user),
    db:Session=Depends(get_db)):
    _need_any(db,m,u,"lab.manage")
    ids=payload.get("test_ids")
    if not isinstance(ids,list) or not ids or len(ids)>100 or len(ids)!=len(set(ids)):
        raise HTTPException(422,"Panel requires unique test IDs")
    tests=[]
    for tid in ids:
        row,data=_get_test(db,m,int(tid));tests.append({"test_id":row.id,"code":data["code"],
            "name":data["name"],"specimen_type":data["specimen_type"]})
    specimen_types={x["specimen_type"] for x in tests}
    if len(specimen_types)!=1:
        raise HTTPException(422,"A laboratory panel must contain tests using the same specimen type")
    code=_required_text(payload,"code",40).upper()
    row=_create(db,m,u,"lab_panel",{"code":code,"name":_required_text(payload,"name"),
        "description":str(payload.get("description",""))[:500],"tests":tests},
        status="active",external_key=code)
    db.commit()
    return {"id":row.id,"code":code,"name":_payload(row)["name"],"test_count":len(tests)}


def _get_test(db,m,test_id):
    row=_get(db,m,test_id,"lab_test")
    data=_payload(row)
    if row.status!="active" or not data.get("is_active",True):raise HTTPException(404,"Active lab test not found")
    return row,data


@router.get("/lab/panels")
def list_laboratory_panels(m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    _need_any(db,m,u,"lab.manage")
    rows=_resource_list(db,m,"lab_panel",status="active",limit=500)
    return [{"id":x.id,**_payload(x)} for x in rows]


@router.post("/lab/orders",status_code=201)
def create_laboratory_order(payload:dict,m=Depends(active_membership),u:User=Depends(current_user),
    db:Session=Depends(get_db)):
    encounter=db.query(HealthcareEncounter).filter_by(
        id=int(payload.get("encounter_id",0)),organization_id=m.organization_id,status="open").first()
    if not encounter or encounter.clinician_user_id!=u.id:
        raise HTTPException(403,"Lab order requires an open encounter assigned to the current clinician")
    patient,emergency,_=_patient_write(db,m,u,encounter.patient_id)
    _need(db,m,u,"orders.manage",patient.branch_id)
    test_ids=payload.get("test_ids") or []
    if payload.get("panel_id"):
        panel=_get(db,m,int(payload["panel_id"]),"lab_panel")
        test_ids=[x["test_id"] for x in _payload(panel)["tests"]]
    if not isinstance(test_ids,list) or not 1<=len(test_ids)<=100 or len(test_ids)!=len(set(test_ids)):
        raise HTTPException(422,"Lab order requires unique test IDs")
    lines=[]
    for tid in test_ids:
        row,data=_get_test(db,m,int(tid))
        lines.append({"test_id":row.id,"test_code":data["code"],"test_name":data["name"],
            "specimen_type":data["specimen_type"],"unit":data["unit"],
            "reference_range":data["reference_range"],"price":data["price"],
            "status":"pending","result_value":"","result_notes":"","entered_by":None,"validated_by":None})
    if len({x["specimen_type"] for x in lines})!=1:
        raise HTTPException(422,"Different specimen types must be ordered separately")
    client=_required_text(payload,"client_order_id",100)
    data={"client_order_id":client,"encounter_id":encounter.id,"patient_id":patient.id,
        "ordering_clinician_id":u.id,"lines":lines,"status":"ordered","ordered_at":NOW().isoformat()}
    row=_create(db,m,u,"lab_order",data,patient.branch_id,patient.id,status="ordered",
        external_key=client,idempotency_key=client)
    _patient_event(db,m,u,patient,"lab.order.created",{"order_id":row.id,"test_count":len(lines)},row.id,client)
    db.commit()
    return {"id":row.id,"patient_id":patient.id,"status":row.status,"lines":lines}


@router.get("/lab/orders")
def list_laboratory_orders(status:str|None=None,patient_id:int|None=None,branch_id:str|None=None,
    m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db),
    limit:int=Query(200,ge=1,le=500)):
    if patient_id:
        patient,_,_=_patient_read(db,m,u,patient_id)
        branch_id=branch_id or patient.branch_id
    _need(db,m,u,"lab.manage",branch_id)
    rows=_resource_list(db,m,"lab_order",branch_id=branch_id,patient_id=patient_id,status=status,limit=limit)
    return [{"id":x.id,"patient_id":x.patient_id,"branch_id":x.branch_id,"status":x.status,
        "encounter_id":_payload(x).get("encounter_id"),"created_at":x.created_at.isoformat()} for x in rows]


@router.get("/lab/orders/{order_id}")
def get_laboratory_order(order_id:int,m=Depends(active_membership),u:User=Depends(current_user),
    db:Session=Depends(get_db)):
    row=_get(db,m,order_id,"lab_order")
    _need(db,m,u,"lab.manage",row.branch_id);_patient_read(db,m,u,row.patient_id)
    samples=_resource_list(db,m,"lab_sample",branch_id=row.branch_id,patient_id=row.patient_id,limit=1000)
    samples=[x for x in samples if x.parent_id==row.id]
    return {**_view(row),"samples":[_view(x) for x in samples]}


@router.post("/lab/orders/{order_id}/start-processing")
def start_laboratory_processing(order_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    order=_get(db,m,order_id,"lab_order",lock=True)
    _need(db,m,u,"lab.manage",order.branch_id)
    if order.status not in {"sample_collected","processing"}:
        raise HTTPException(409,"Order is not ready for processing")
    samples=_resource_list(db,m,"lab_sample",branch_id=order.branch_id,
        patient_id=order.patient_id,limit=1000)
    if not any(x.parent_id==order.id and x.status=="accepted" for x in samples):
        raise HTTPException(409,"At least one accepted sample is required")
    data=_payload(order);data["status"]="processing"
    data["processing_started_at"]=data.get("processing_started_at") or NOW().isoformat()
    data["processing_started_by"]=u.id
    _update(order,data,u,status="processing")
    patient=_patient(db,order.patient_id,m)
    _patient_event(db,m,u,patient,"lab.order.processing_started",
        {"order_id":order.id},order.id)
    db.commit()
    return {"order_id":order.id,"status":order.status}


@router.post("/lab/orders/{order_id}/samples",status_code=201)
def collect_laboratory_sample(order_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    order=_get(db,m,order_id,"lab_order",lock=True)
    _need(db,m,u,"lab.manage",order.branch_id);patient,_,_=_patient_read(db,m,u,order.patient_id)
    od=_payload(order)
    if order.status not in {"ordered","sample_collected","sample_rejected"}:
        raise HTTPException(409,"Order is not accepting specimens")
    accession=_required_text(payload,"accession_number",80).upper()
    specimen=_required_text(payload,"specimen_type",80).lower()
    if specimen not in {x["specimen_type"] for x in od["lines"]}:
        raise HTTPException(422,"Specimen type does not match the ordered tests")
    duplicate=_resource_list(db,m,"lab_sample",branch_id=order.branch_id,patient_id=patient.id,limit=1000)
    if any(_payload(x).get("accession_number")==accession for x in duplicate):
        raise HTTPException(409,"Accession number already exists")
    data={"order_id":order.id,"accession_number":accession,"barcode_value":accession,
        "specimen_type":specimen,"status":"collected","collected_by":u.id,
        "collected_at":NOW().isoformat(),"chain":[{"action":"collected","actor_id":u.id,"at":NOW().isoformat()}]}
    sample=_create(db,m,u,"lab_sample",data,order.branch_id,patient.id,parent_id=order.id,status="collected",
        external_key=accession)
    od["status"]="sample_collected";_update(order,od,u,status="sample_collected")
    _patient_event(db,m,u,patient,"lab.sample.collected",{"sample_id":sample.id,
        "accession_number":accession,"specimen_type":specimen},sample.id)
    db.commit()
    return {"id":sample.id,"accession_number":accession,"barcode_value":accession,"status":sample.status}


@router.post("/lab/samples/{sample_id}/custody")
def record_laboratory_sample_custody(sample_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    sample=_get(db,m,sample_id,"lab_sample",lock=True)
    _need(db,m,u,"lab.manage",sample.branch_id)
    data=_payload(sample)
    if data.get("status") not in {"collected","in_transit","received"}:
        raise HTTPException(409,"Sample is not in a transferable custody state")
    action=str(payload.get("action",""))
    if action not in {"handoff","received"}:
        raise HTTPException(422,"Custody action must be handoff or received")
    recipient_id=int(payload.get("recipient_user_id",0))
    recipient=db.query(User).filter_by(id=recipient_id,is_active=True).first()
    recipient_membership=db.query(Membership).filter_by(
        organization_id=m.organization_id,user_id=recipient_id,is_active=True).first()
    if not recipient or not recipient_membership:
        raise HTTPException(422,"Custody recipient must be an active organization member")
    from app.api.healthcare_hospital import _roles
    if not _roles(db,m,recipient,sample.branch_id).intersection(LAB_ROLES):
        raise HTTPException(403,"Custody recipient must have laboratory access at this branch")
    location=_required_text(payload,"location",160)
    event_key=_required_text(payload,"idempotency_key",100)
    chain=data.setdefault("chain",[])
    prior=next((x for x in chain if x.get("idempotency_key")==event_key),None)
    if prior:
        if prior.get("action")!=action or prior.get("recipient_user_id")!=recipient_id:
            raise HTTPException(409,"Sample custody idempotency key conflicts with an earlier event")
        return {"sample_id":sample.id,"status":"already_recorded","custody_events":len(chain)}
    chain.append({"action":action,"actor_id":u.id,
        "recipient_user_id":recipient_id,"location":location,"at":NOW().isoformat(),
        "seal_number":str(payload.get("seal_number",""))[:100],"idempotency_key":event_key})
    data["status"]="in_transit" if action=="handoff" else "received"
    _update(sample,data,u,status=data["status"])
    patient=_patient(db,sample.patient_id,m)
    _patient_event(db,m,u,patient,"lab.sample.custody."+action,
        {"sample_id":sample.id,"recipient_user_id":recipient_id,"location":location},sample.id,event_key)
    db.commit()
    return {"sample_id":sample.id,"status":sample.status,"custody_events":len(data["chain"])}


@router.post("/lab/samples/{sample_id}/decision")
def decide_laboratory_sample(sample_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    sample=_get(db,m,sample_id,"lab_sample",lock=True)
    _need(db,m,u,"lab.manage",sample.branch_id);patient,_,_=_patient_read(db,m,u,sample.patient_id)
    data=_payload(sample);decision=str(payload.get("decision",""))
    reason=_required_text(payload,"reason",500)
    if decision not in {"accepted","rejected"}:raise HTTPException(422,"Decision must be accepted or rejected")
    if data["status"] not in {"collected","received"}:raise HTTPException(409,"Sample cannot transition from current state")
    data["status"]=decision;data["chain"].append({"action":decision,"actor_id":u.id,
        "reason":reason,"at":NOW().isoformat()})
    _update(sample,data,u,status=decision)
    order=_get(db,m,int(data["order_id"]),"lab_order",lock=True);od=_payload(order)
    accepted=_resource_list(db,m,"lab_sample",branch_id=order.branch_id,patient_id=patient.id,limit=1000)
    any_accepted=any(x.id!=sample.id and _payload(x).get("status")=="accepted" for x in accepted)
    od["status"]="sample_collected" if decision=="accepted" or any_accepted else "sample_rejected"
    _update(order,od,u,status=od["status"])
    _patient_event(db,m,u,patient,f"lab.sample.{decision}",
        {"sample_id":sample.id,"reason":reason},sample.id)
    db.commit()
    return {"sample_id":sample.id,"status":sample.status,"order_status":order.status}


@router.post("/lab/orders/{order_id}/results")
def enter_laboratory_result(order_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    order=_get(db,m,order_id,"lab_order",lock=True)
    _need(db,m,u,"lab.manage",order.branch_id);patient,_,_=_patient_read(db,m,u,order.patient_id)
    od=_payload(order)
    if od["status"] not in {"sample_collected","processing","results_entered"}:
        raise HTTPException(409,"Accepted sample required before result entry")
    samples=_resource_list(db,m,"lab_sample",branch_id=order.branch_id,patient_id=patient.id,limit=1000)
    if not any(x.parent_id==order.id and _payload(x).get("status")=="accepted" for x in samples):
        raise HTTPException(409,"At least one accepted sample is required")
    idx=int(payload.get("line_index",-1))
    if idx<0 or idx>=len(od["lines"]):raise HTTPException(404,"Test line not found")
    line=od["lines"][idx]
    if line["status"]!="pending":raise HTTPException(409,"Result already entered")
    result=_required_text(payload,"result_value",4000)
    line["result_value"]=result;line["result_notes"]=str(payload.get("result_notes",""))[:4000]
    line["entered_by"]=u.id;line["status"]="entered"
    od["lines"][idx]=line
    od["status"]="results_entered" if all(x["status"]=="entered" for x in od["lines"]) else "processing"
    _update(order,od,u,status=od["status"])
    critical=_critical_result(line,result,bool(payload.get("is_critical")))
    line["is_critical"]=critical;od["lines"][idx]=line
    _update(order,od,u,status=od["status"])
    if critical:
        alert=_create(db,m,u,"lab_critical_alert",{"order_id":order.id,"line_index":idx,
            "patient_id":patient.id,"test_code":line["test_code"],"result_value":result,
            "status":"queued","escalation_required":True},order.branch_id,patient.id,
            parent_id=order.id,status="queued")
        _patient_event(db,m,u,patient,"lab.critical_result.queued",{"alert_id":alert.id},alert.id)
    _patient_event(db,m,u,patient,"lab.result.entered",{"order_id":order.id,
        "line_index":idx,"critical":bool(payload.get("is_critical"))},order.id)
    db.commit()
    return {"order_id":order.id,"line_index":idx,"status":line["status"],"order_status":order.status}


@router.post("/lab/orders/{order_id}/validate")
def validate_laboratory_order(order_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    order=_get(db,m,order_id,"lab_order",lock=True)
    _need(db,m,u,"lab.manage",order.branch_id);patient,_,_=_patient_read(db,m,u,order.patient_id)
    od=_payload(order)
    if od["status"]!="results_entered" or any(x["status"]!="entered" for x in od["lines"]):
        raise HTTPException(409,"All test results must be entered before validation")
    if any(x["entered_by"]==u.id for x in od["lines"]):
        raise HTTPException(403,"A result author cannot validate their own results")
    note=_required_text(payload,"note",500)
    validated_at=NOW().isoformat()
    for line in od["lines"]:
        line["status"]="validated";line["validated_by"]=u.id;line["validated_at"]=validated_at
    od["status"]="validated";od["validated_by"]=u.id;od["validated_at"]=validated_at;od["validation_note"]=note
    _update(order,od,u,status="validated")
    _patient_event(db,m,u,patient,"lab.order.validated",{"order_id":order.id,"note":note},order.id)
    db.commit()
    return {"order_id":order.id,"status":"validated","validated_lines":len(od["lines"])}


# ---------------- Analyzer equipment, QC and calibration ----------------

@router.post("/lab/instruments",status_code=201)
def register_laboratory_instrument(payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    branch_id=_required_text(payload,"branch_id",36)
    _need(db,m,u,"lab.manage",branch_id)
    branch=db.query(Branch).filter_by(id=branch_id,organization_id=m.organization_id,is_active=True).first()
    if not branch:raise HTTPException(404,"Active branch not found")
    name=_required_text(payload,"name",180)
    secret=secrets.token_urlsafe(40)
    data={"name":name,"manufacturer":str(payload.get("manufacturer",""))[:120],
        "model":str(payload.get("model",""))[:120],"api_key_hash":hashlib.sha256(secret.encode()).hexdigest(),
        "registered_by":u.id,"last_seen_at":None}
    row=_create(db,m,u,"lab_instrument",data,branch_id=branch_id,status="active")
    _audit_action(db,m,u,"lab.instrument.registered","lab_instrument",row.id,name)
    db.commit()
    return {"id":row.id,"status":"active","instrument_key":secret,
        "warning":"Store this key securely; it is returned only once."}


@router.post("/lab/instruments/{instrument_id}/rotate-key")
def rotate_laboratory_instrument_key(instrument_id:int,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    instrument=_get(db,m,instrument_id,"lab_instrument",lock=True)
    _need(db,m,u,"lab.manage",instrument.branch_id)
    if instrument.status!="active":raise HTTPException(409,"Only active instruments can rotate credentials")
    data=_payload(instrument);secret=secrets.token_urlsafe(40)
    data["api_key_hash"]=hashlib.sha256(secret.encode()).hexdigest()
    data["key_rotated_at"]=NOW().isoformat();data["key_rotated_by"]=u.id
    _update(instrument,data,u)
    _audit_action(db,m,u,"lab.instrument.key_rotated","lab_instrument",instrument.id)
    db.commit()
    return {"id":instrument.id,"instrument_key":secret,"warning":"Store this key securely; it is returned only once."}


@router.post("/lab/instruments/{instrument_id}/revoke")
def revoke_laboratory_instrument(instrument_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    instrument=_get(db,m,instrument_id,"lab_instrument",lock=True)
    _need(db,m,u,"lab.manage",instrument.branch_id)
    reason=_required_text(payload,"reason",500)
    data=_payload(instrument);data["api_key_hash"]="";data["revoked_at"]=NOW().isoformat()
    data["revoked_by"]=u.id;data["revocation_reason"]=reason
    _update(instrument,data,u,status="revoked")
    _audit_action(db,m,u,"lab.instrument.revoked","lab_instrument",instrument.id,reason)
    db.commit()
    return {"id":instrument.id,"status":instrument.status}


@router.post("/lab/instruments/{instrument_id}/qc")
def record_laboratory_qc(instrument_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    instrument=_get(db,m,instrument_id,"lab_instrument")
    _need(db,m,u,"lab.manage",instrument.branch_id)
    if instrument.status!="active":raise HTTPException(409,"Inactive instrument cannot receive QC")
    passed=bool(payload.get("passed"))
    valid_until=_date(payload.get("valid_until"),"valid_until")
    if valid_until<date.today():raise HTTPException(422,"QC validity date cannot be in the past")
    data={"instrument_id":instrument.id,"control_lot":_required_text(payload,"control_lot",80),
        "result":_required_text(payload,"result",200),"expected_range":_required_text(payload,"expected_range",120),
        "valid_until":valid_until.isoformat(),"passed":passed,"recorded_by":u.id,"recorded_at":NOW().isoformat()}
    row=_create(db,m,u,"lab_qc",data,instrument.branch_id,parent_id=instrument.id,
        status="passed" if passed else "failed")
    _audit_action(db,m,u,"lab.quality_control.recorded","lab_qc",row.id,row.status)
    db.commit()
    return {"id":row.id,"status":row.status,"instrument_blocked":not passed}


@router.post("/lab/instruments/{instrument_id}/calibration")
def record_laboratory_calibration(instrument_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    instrument=_get(db,m,instrument_id,"lab_instrument")
    _need(db,m,u,"lab.manage",instrument.branch_id)
    if instrument.status!="active":raise HTTPException(409,"Inactive instrument cannot be calibrated")
    outcome=str(payload.get("outcome",""))
    if outcome not in {"passed","failed"}:raise HTTPException(422,"Calibration outcome must be passed or failed")
    next_due=_date(payload.get("next_due"),"next_due")
    if next_due<date.today():raise HTTPException(422,"Calibration due date cannot be in the past")
    data={"instrument_id":instrument.id,"reference":_required_text(payload,"calibration_reference",120),
        "outcome":outcome,"next_due":next_due.isoformat(),"recorded_by":u.id,
        "recorded_at":NOW().isoformat()}
    row=_create(db,m,u,"lab_calibration",data,instrument.branch_id,parent_id=instrument.id,status=outcome)
    _audit_action(db,m,u,"lab.calibration.recorded","lab_calibration",row.id,outcome)
    db.commit()
    return {"id":row.id,"status":row.status,"next_due":next_due.isoformat()}


@router.post("/lab/instruments/{instrument_id}/results")
def receive_analyzer_result(instrument_id:int,payload:dict,
    x_instrument_key:str=Header(...,alias="X-Instrument-Key",min_length=32),
    db:Session=Depends(get_db)):
    instrument=db.query(HealthcareResource).filter_by(
        id=instrument_id,resource_type="lab_instrument").with_for_update().first()
    if not instrument:
        raise HTTPException(404,"Analyzer instrument not found")
    data=_payload(instrument)
    supplied=hashlib.sha256(x_instrument_key.encode()).hexdigest()
    if not hmac.compare_digest(data.get("api_key_hash",""),supplied):
        raise HTTPException(401,"Invalid analyzer credential")
    if instrument.status!="active":
        raise HTTPException(409,"Analyzer instrument is revoked or inactive")
    m=db.query(Membership).filter_by(organization_id=instrument.organization_id,
        user_id=data.get("registered_by"),is_active=True).first()
    u=db.query(User).filter_by(id=data.get("registered_by"),is_active=True).first()
    if not m or not u or not can_access_branch(m,instrument.branch_id):
        raise HTTPException(401,"Analyzer registration owner is no longer authorized")

    latest_qc=_resource_list(db,m,"lab_qc",branch_id=instrument.branch_id,limit=1000)
    latest_qc=next((x for x in latest_qc if x.parent_id==instrument.id),None)
    if (not latest_qc or latest_qc.status!="passed"
        or _date(_payload(latest_qc).get("valid_until"),"QC valid_until")<date.today()):
        raise HTTPException(409,"A current passing QC record is required")
    latest_cal=_resource_list(db,m,"lab_calibration",branch_id=instrument.branch_id,limit=1000)
    latest_cal=next((x for x in latest_cal if x.parent_id==instrument.id),None)
    if not latest_cal or latest_cal.status!="passed" or _date(_payload(latest_cal)["next_due"],"next_due")<date.today():
        raise HTTPException(409,"A current passing calibration is required")
    result_id=_required_text(payload,"result_id",120)
    accession=_required_text(payload,"accession_number",80).upper()
    samples=_resource_list(db,m,"lab_sample",branch_id=instrument.branch_id,limit=1000)
    sample=next((x for x in samples if _payload(x).get("accession_number")==accession and _payload(x).get("status")=="accepted"),None)
    if not sample:raise HTTPException(404,"Accepted sample accession not found")
    order=_get(db,m,sample.parent_id,"lab_order",lock=True);od=_payload(order)
    code=_required_text(payload,"test_code",40).upper()
    result_value=_required_text(payload,"result_value",4000)
    prior_result=next((x for x in od["lines"] if x.get("analyzer_result_id")==result_id),None)
    if prior_result:
        if prior_result.get("test_code")!=code or prior_result.get("result_value")!=result_value or prior_result.get("instrument_id")!=instrument.id:
            raise HTTPException(409,"Analyzer result ID conflicts with a previously received result")
        return {"order_id":order.id,"status":"already_recorded","critical_alert":bool(prior_result.get("is_critical"))}
    idx=next((i for i,x in enumerate(od["lines"]) if x["test_code"]==code and x["status"]=="pending"),None)
    if idx is None:raise HTTPException(409,"No pending order line matches the analyzer test code")
    line=od["lines"][idx];line["result_value"]=result_value
    line["analyzer_result_id"]=result_id
    line["result_notes"]=str(payload.get("result_notes",""))[:4000]
    line["entered_by"]=data["registered_by"];line["instrument_id"]=instrument.id;line["status"]="entered"
    od["lines"][idx]=line;od["status"]="results_entered" if all(x["status"]=="entered" for x in od["lines"]) else "processing"
    _update(order,od,u,status=od["status"])
    data["last_seen_at"]=NOW().isoformat();_update(instrument,data,u)
    critical=_critical_result(line,line["result_value"],bool(payload.get("is_critical")))
    line["is_critical"]=critical;od["lines"][idx]=line
    _update(order,od,u,status=od["status"])
    if critical:
        alert=_create(db,m,u,"lab_critical_alert",{"order_id":order.id,"line_index":idx,
            "patient_id":order.patient_id,"test_code":code,"result_value":line["result_value"],
            "status":"queued","escalation_required":True},order.branch_id,order.patient_id,
            parent_id=order.id,status="queued")
        _patient_event(db,m,u,_patient(db,order.patient_id,m),"lab.critical_result.queued",{"alert_id":alert.id},alert.id)
    _patient_event(db,m,u,_patient(db,order.patient_id,m),"lab.instrument.result_received",
        {"instrument_id":instrument.id,"order_id":order.id,"line_index":idx},order.id)
    db.commit()
    return {"order_id":order.id,"line_index":idx,"status":"entered","critical_alert":critical}


@router.get("/lab/critical-alerts")
def list_laboratory_critical_alerts(status:str|None=None,branch_id:str|None=None,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    _need(db,m,u,"lab.manage",branch_id)
    rows=_resource_list(db,m,"lab_critical_alert",branch_id=branch_id,status=status,limit=500)
    return [_view(x) for x in rows]


@router.post("/lab/critical-alerts/{alert_id}/acknowledge")
def acknowledge_laboratory_critical_alert(alert_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    alert=_get(db,m,alert_id,"lab_critical_alert",lock=True)
    _need(db,m,u,"lab.manage",alert.branch_id)
    if alert.status!="queued":raise HTTPException(409,"Critical alert is no longer awaiting acknowledgement")
    data=_payload(alert);data["acknowledged_by"]=u.id
    data["acknowledged_at"]=NOW().isoformat();data["acknowledgement_note"]=_required_text(payload,"note",500)
    _update(alert,data,u,status="acknowledged")
    patient=_patient(db,alert.patient_id,m)
    _patient_event(db,m,u,patient,"lab.critical_alert.acknowledged",{"alert_id":alert.id},alert.id)
    db.commit()
    return {"id":alert.id,"status":alert.status}


# ---------------- Secure results, billing and insurance ----------------

@router.post("/lab/orders/{order_id}/deliver")
def queue_laboratory_result_delivery(order_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    order=_get(db,m,order_id,"lab_order")
    _need(db,m,u,"lab.manage",order.branch_id)
    patient,_,_=_patient_read(db,m,u,order.patient_id)
    if order.status!="validated":raise HTTPException(409,"Only validated results can be delivered")
    od=_payload(order);recipient_type=str(payload.get("recipient_type","clinician"))
    if recipient_type not in {"clinician","patient"}:raise HTTPException(422,"Invalid recipient type")
    recipient_id=int(payload.get("recipient_id") or (od["ordering_clinician_id"] if recipient_type=="clinician" else patient.id))
    if recipient_type=="clinician":
        recipient=db.query(User).filter_by(id=recipient_id,is_active=True).first()
        member=db.query(Membership).filter_by(organization_id=m.organization_id,
            user_id=recipient_id,is_active=True).first()
        from app.api.healthcare_hospital import _roles
        if not recipient or not member or not _roles(db,m,recipient,order.branch_id).intersection({"clinician","healthcare_admin"}):
            raise HTTPException(403,"Result recipient must be an active clinician in this organization")
        if recipient_id!=od["ordering_clinician_id"] and "healthcare_admin" not in _roles(db,m,u,order.branch_id):
            raise HTTPException(403,"Only the ordering clinician or healthcare administrator may redirect results")
    token=secrets.token_urlsafe(40) if recipient_type=="patient" else None
    data={"order_id":order.id,"recipient_type":recipient_type,"recipient_id":recipient_id,
        "results":[{"test_code":x["test_code"],"test_name":x["test_name"],
            "result_value":x["result_value"],"unit":x["unit"],"reference_range":x["reference_range"]}
            for x in od["lines"]],"channel":"secure_in_app","delivery_status":"queued"}
    if token:
        data["token_hash"]=hashlib.sha256(token.encode()).hexdigest()
        data["expires_at"]=(NOW()+timedelta(days=7)).isoformat()
    row=_create(db,m,u,"lab_delivery",data,order.branch_id,patient.id,parent_id=order.id,status="queued")
    _patient_event(db,m,u,patient,"lab.result.delivery_queued",{"delivery_id":row.id,"recipient_type":recipient_type},row.id)
    db.commit()
    return {"delivery_id":row.id,"status":row.status,"patient_access_token":token,
        "expires_in_days":7 if token else None,"channel":"secure_in_app"}


@router.get("/lab/deliveries/{delivery_id}")
def get_laboratory_delivery(delivery_id:int,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    row=_get(db,m,delivery_id,"lab_delivery")
    data=_payload(row)
    if data["recipient_type"]!="clinician" or data["recipient_id"]!=u.id:
        raise HTTPException(403,"Delivery is not addressed to this clinician")
    patient,_,_=_patient_read(db,m,u,row.patient_id)
    _patient_event(db,m,u,patient,"lab.result.delivery_accessed",{"delivery_id":row.id},row.id)
    db.commit()
    return {"id":row.id,"results":data["results"],"status":row.status}


@router.get("/lab/public-deliveries/{delivery_id}")
def get_patient_laboratory_delivery(delivery_id:int,x_delivery_token:str=Header(...,alias="X-Delivery-Token",min_length=32),
    db:Session=Depends(get_db)):
    row=db.query(HealthcareResource).filter_by(id=delivery_id,resource_type="lab_delivery",status="queued").with_for_update().first()
    if not row:raise HTTPException(404,"Secure result delivery not found")
    data=decrypt(row.encrypted_payload)
    expected=data.get("token_hash","")
    if data.get("recipient_type")!="patient" or not hmac.compare_digest(expected,hashlib.sha256(x_delivery_token.encode()).hexdigest()):
        raise HTTPException(403,"Invalid result delivery token")
    if not data.get("expires_at") or datetime.fromisoformat(data["expires_at"])<NOW():
        raise HTTPException(410,"Result delivery token expired")
    row.status="accessed";data["accessed_at"]=NOW().isoformat();row.encrypted_payload=encrypt(data)
    db.commit()
    return {"delivery_id":row.id,"results":data["results"],"status":"accessed"}


@router.post("/pharmacy-lab/billing")
def create_pharmacy_lab_invoice(payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    patient_id=int(payload.get("patient_id",0))
    patient,_,_=_patient_access(db,m,u,patient_id,"patient.read",write=False)
    _need(db,m,u,"billing.manage",patient.branch_id)
    source_type=str(payload.get("source_type",""));source_id=int(payload.get("source_id",0))
    amount=_money(payload.get("amount"))
    if source_type=="pharmacy_dispense":
        source=_get(db,m,source_id,"pharmacy_dispense")
        if source.patient_id!=patient.id:raise HTTPException(422,"Invoice patient does not match dispense")
        expected=source.amount
        if amount!=expected:raise HTTPException(422,"Pharmacy invoice amount must match the dispense total")
    elif source_type=="laboratory_order":
        source=_get(db,m,source_id,"lab_order")
        if source.patient_id!=patient.id or source.status!="validated":raise HTTPException(409,"Only validated patient lab orders can be billed")
        od=_payload(source)
        expected=sum((_money(x["price"]) for x in od["lines"]),Decimal("0.00"))
        if amount!=expected:raise HTTPException(422,"Laboratory invoice must match the configured test catalogue prices")
    else:raise HTTPException(422,"Unsupported invoice source type")
    currency=str(payload.get("currency","KES")).upper()
    if len(currency)!=3 or not currency.isalpha():
        raise HTTPException(422,"Currency must be a three-letter ISO code")
    data={"patient_id":patient.id,"source_type":source_type,"source_id":source_id,
        "invoice_number":str(payload.get("invoice_number") or f"CLIN-{source_type[:3].upper()}-{source_id}"),
        "amount":str(amount),"currency":currency,"status":"unpaid",
        "created_at":NOW().isoformat()}
    invoice=_create(db,m,u,"invoice",data,patient.branch_id,patient.id,parent_id=source.id,
        status="unpaid",amount=amount,currency=data["currency"],
        idempotency_key=f"clinical-invoice:{source_type}:{source_id}")
    claim_id=None
    if str(payload.get("insurer_name","")).strip():
        _need(db,m,u,"insurance.manage",patient.branch_id)
        claim=_create(db,m,u,"insurance_claim",{"invoice_id":invoice.id,
            "insurer_name":str(payload["insurer_name"]).strip()[:180],
            "policy_number":str(payload.get("policy_number",""))[:100],
            "amount":str(amount),"status":"submitted","submitted_at":NOW().isoformat()},
            patient.branch_id,patient.id,parent_id=invoice.id,status="submitted",
            idempotency_key=f"clinical-claim:{invoice.id}")
        claim_id=claim.id
    _patient_event(db,m,u,patient,"clinical.invoice.created",{"invoice_id":invoice.id,
        "claim_id":claim_id,"amount":str(amount)},invoice.id)
    db.commit()
    return {"invoice_id":invoice.id,"status":invoice.status,"claim_id":claim_id}


@router.post("/pharmacy-lab/claims/{claim_id}/decision")
def decide_pharmacy_lab_claim(claim_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    claim=_get(db,m,claim_id,"insurance_claim",lock=True)
    _need(db,m,u,"insurance.manage",claim.branch_id)
    if claim.status!="submitted":raise HTTPException(409,"Only submitted claims can receive an insurer decision")
    decision=str(payload.get("decision",""))
    if decision not in {"approved","rejected"}:raise HTTPException(422,"Decision must be approved or rejected; use the settlement endpoint to reconcile payment")
    data=_payload(claim);data.update({"decision_note":_required_text(payload,"note",500),
        "decided_by":u.id,"decided_at":NOW().isoformat(),"status":decision})
    _update(claim,data,u,status=decision)
    _audit_action(db,m,u,"clinical.insurance_claim."+decision,"insurance_claim",claim.id)
    db.commit()
    return {"claim_id":claim.id,"status":claim.status}


@router.post("/pharmacy-lab/claims/{claim_id}/settle")
def settle_pharmacy_lab_claim(claim_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    claim=_get(db,m,claim_id,"insurance_claim",lock=True)
    _need(db,m,u,"insurance.manage",claim.branch_id)
    if claim.status not in {"approved","partially_settled"}:
        raise HTTPException(409,"Only approved claims can be settled")
    from app.api.healthcare_hospital import settle_claim
    return settle_claim(claim_id,payload,m,u,db)


@router.get("/pharmacy/reports/stock")
def pharmacy_stock_report(branch_id:str,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db),near_expiry_days:int=Query(90,ge=1,le=365)):
    _need(db,m,u,"pharmacy.manage",branch_id)
    cutoff=date.today();expiry_cutoff=cutoff+timedelta(days=near_expiry_days)
    rows=_resource_list(db,m,"pharmacy_batch",branch_id=branch_id,limit=5000)
    totals={};expired=near=quarantined=recalled=0
    for row in rows:
        data=_payload(row);medicine_id=int(data["medicine_id"])
        bucket=totals.setdefault(medicine_id,{"medicine_id":medicine_id,"received":Decimal("0"),
            "available":Decimal("0"),"unit_cost_value":Decimal("0"),"batch_count":0})
        bucket["batch_count"]+=1
        bucket["received"]+=Decimal(data["received_quantity"])
        remaining=Decimal(data["remaining_quantity"])
        if row.status=="active":
            expiry=_date(data["expiry_date"],"expiry_date")
            if expiry<cutoff:
                expired+=1
            else:
                bucket["available"]+=remaining
                if expiry<=expiry_cutoff and remaining>0:near+=1
            bucket["unit_cost_value"]+=remaining*Decimal(data["unit_cost"])
        elif row.status=="quarantined":quarantined+=1
        elif row.status=="recalled":recalled+=1
    return {"branch_id":branch_id,"as_of":cutoff.isoformat(),"near_expiry_days":near_expiry_days,
        "summary":{"medicine_count":len(totals),"expired_batches":expired,
            "near_expiry_batches":near,"quarantined_batches":quarantined,"recalled_batches":recalled},
        "medicines":[{"medicine_id":v["medicine_id"],"batch_count":v["batch_count"],
            "received_quantity":str(v["received"]),"available_quantity":str(v["available"]),
            "inventory_cost_value":str(v["unit_cost_value"].quantize(Decimal("0.01")))}
            for v in totals.values()]}


@router.get("/lab/reports/operations")
def laboratory_operations_report(branch_id:str,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    _need(db,m,u,"lab.manage",branch_id)
    orders=_resource_list(db,m,"lab_order",branch_id=branch_id,limit=5000)
    samples=_resource_list(db,m,"lab_sample",branch_id=branch_id,limit=5000)
    alerts=_resource_list(db,m,"lab_critical_alert",branch_id=branch_id,limit=5000)
    counts={}
    turnaround=[]
    for order in orders:
        counts[order.status]=counts.get(order.status,0)+1
        data=_payload(order)
        if order.status=="validated" and data.get("ordered_at") and data.get("validated_at"):
            start=datetime.fromisoformat(data["ordered_at"]);end=datetime.fromisoformat(data["validated_at"])
            turnaround.append(max(0,(end-start).total_seconds()/3600))
    sample_counts={}
    for sample in samples:sample_counts[sample.status]=sample_counts.get(sample.status,0)+1
    alert_counts={}
    for alert in alerts:alert_counts[alert.status]=alert_counts.get(alert.status,0)+1
    average=round(sum(turnaround)/len(turnaround),2) if turnaround else None
    return {"branch_id":branch_id,"as_of":NOW().isoformat(),
        "orders":{"total":len(orders),"by_status":counts,"validated_average_turnaround_hours":average},
        "samples":{"total":len(samples),"by_status":sample_counts},
        "critical_alerts":{"total":len(alerts),"by_status":alert_counts,
            "unacknowledged":sum(1 for x in alerts if x.status=="queued")}}


@router.get("/pharmacy-lab/traceability")
def pharmacy_lab_traceability(patient_id:int|None=None,resource_type:str|None=None,
    m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db),
    limit:int=Query(200,ge=1,le=1000)):
    if patient_id is not None:
        patient=_patient(db,patient_id,m)
        _require(db,m,u,"audit.read",patient.branch_id,patient.id,True)
        q=db.query(HealthcareEvent).filter_by(organization_id=m.organization_id,patient_id=patient.id)
        events=q.order_by(HealthcareEvent.occurred_at.desc()).limit(limit).all()
        return [{"id":x.id,"event_type":x.event_type,"resource_id":x.resource_id,
            "occurred_at":x.occurred_at.isoformat(),"detail":decrypt(x.encrypted_detail)} for x in events]
    _require(db,m,u,"audit.read",allow_unscoped=True)
    q=db.query(HealthcareResource).filter(HealthcareResource.organization_id==m.organization_id)
    if resource_type:q=q.filter(HealthcareResource.resource_type==resource_type)
    allowed=branch_scope_ids(m)
    if allowed is not None:q=q.filter(HealthcareResource.branch_id.in_(allowed))
    rows=q.order_by(HealthcareResource.created_at.desc()).limit(limit).all()
    return [_view(x) for x in rows]
