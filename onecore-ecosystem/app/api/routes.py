import json, re, uuid
from decimal import Decimal
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import User, Organization, Membership, Branch, Record, AuditEvent, InventoryProduct, InventoryStockMovement
from app.core.schemas import OrganizationIn, RecordIn, BranchIn, InventoryProductIn, InventoryMovementIn
from app.core.security import current_user, verify_password, create_access_token, require_platform_admin
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, branch_scope_ids, can_access_branch
from app.integrations.registry import public_provider_status
from app.services.inventory import validate_stock_delta, resulting_balance

router = APIRouter(prefix="/api/v1")
CATALOG_PATH = Path(__file__).resolve().parents[1] / "modules" / "catalog.json"

def audit(db, user_id, org_id, action, resource_type="", resource_id="", detail=""):
    db.add(AuditEvent(actor_user_id=user_id, organization_id=org_id, action=action,
                      resource_type=resource_type, resource_id=str(resource_id), detail=detail))
    db.commit()

def validate_module_key(module_key: str):
    if not re.fullmatch(r"[a-z0-9-]{2,100}", module_key):
        raise HTTPException(400, "Invalid module key")

@router.post("/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form.username.lower()).first()
    if not user or not verify_password(form.password, user.password_hash) or not user.is_active:
        raise HTTPException(401, "Incorrect email or password")
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}

@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "platform_role": user.platform_role}

@router.post("/organizations", status_code=201)
def create_organization(payload: OrganizationIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if db.query(Organization).filter_by(slug=payload.slug).first():
        raise HTTPException(409, "Organization slug already exists")
    org = Organization(**payload.model_dump())
    db.add(org); db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role="org_admin", branch_scope="*"))
    db.commit(); db.refresh(org)
    audit(db, user.id, org.id, "organization.created", "organization", org.id)
    return {"id": org.id, "name": org.name, "slug": org.slug, "role": "org_admin"}

@router.get("/organizations")
def list_organizations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Membership, Organization).join(Organization, Organization.id == Membership.organization_id).filter(
        Membership.user_id == user.id, Membership.is_active == True, Organization.is_active == True).all()
    return [{"id": o.id, "name": o.name, "slug": o.slug, "role": m.role} for m, o in rows]

@router.get("/modules")
def module_catalog(user: User = Depends(current_user)):
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

@router.get("/integrations")
def integrations(user: User = Depends(current_user)):
    return public_provider_status()


@router.get("/branches")
def list_branches(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    query=db.query(Branch).filter_by(organization_id=membership.organization_id,is_active=True)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed: return []
        query=query.filter(Branch.id.in_(allowed))
    return [{"id":b.id,"code":b.code,"name":b.name,"address":b.address} for b in query.order_by(Branch.name).all()]

@router.post("/branches",status_code=201)
def create_branch(payload:BranchIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    if db.query(Branch).filter_by(organization_id=membership.organization_id,code=payload.code).first():
        raise HTTPException(409,"Branch code already exists in this organization")
    row=Branch(id=str(uuid.uuid4()),organization_id=membership.organization_id,code=payload.code,name=payload.name,address=payload.address)
    db.add(row);db.commit();db.refresh(row)
    audit(db,user.id,membership.organization_id,"branch.created","branch",row.id)
    return {"id":row.id,"code":row.code,"name":row.name,"address":row.address}

@router.put("/branches/{branch_id}")
def update_branch(branch_id:str,payload:BranchIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(Branch).filter_by(id=branch_id,organization_id=membership.organization_id,is_active=True).first()
    if not row: raise HTTPException(404,"Branch not found")
    duplicate=db.query(Branch).filter(Branch.organization_id==membership.organization_id,Branch.code==payload.code,Branch.id!=branch_id).first()
    if duplicate: raise HTTPException(409,"Branch code already exists in this organization")
    row.code=payload.code;row.name=payload.name;row.address=payload.address;db.commit()
    audit(db,user.id,membership.organization_id,"branch.updated","branch",row.id)
    return {"id":row.id,"code":row.code,"name":row.name,"address":row.address}

@router.delete("/branches/{branch_id}",status_code=204)
def deactivate_branch(branch_id:str,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(Branch).filter_by(id=branch_id,organization_id=membership.organization_id,is_active=True).first()
    if not row: raise HTTPException(404,"Branch not found")
    row.is_active=False;db.commit()
    audit(db,user.id,membership.organization_id,"branch.deactivated","branch",row.id)

@router.get("/records/{module_key}")
def list_records(module_key: str, membership=Depends(active_membership), db: Session = Depends(get_db),
                 limit: int = Query(default=100, ge=1, le=500)):
    validate_module_key(module_key)
    require_permission(membership, "read")
    query = db.query(Record).filter_by(organization_id=membership.organization_id, module_key=module_key)
    allowed_branches = branch_scope_ids(membership)
    if allowed_branches is not None:
        if not allowed_branches:
            return []
        query = query.filter(Record.branch_id.in_(allowed_branches))
    rows = query.order_by(Record.id.desc()).limit(limit).all()
    return [{"id": r.id, "module_key": r.module_key, "record_type": r.record_type, "data": r.data,
             "branch_id": r.branch_id, "created_at": r.created_at.isoformat(),
             "updated_at": r.updated_at.isoformat()} for r in rows]

@router.post("/records/{module_key}", status_code=201)
def create_record(module_key: str, payload: RecordIn, membership=Depends(active_membership),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    validate_module_key(module_key)
    require_permission(membership, "create")
    if not can_access_branch(membership, payload.branch_id):
        raise HTTPException(403, "Your membership is not authorized for this branch")
    if payload.branch_id is not None and not db.query(Branch).filter_by(id=payload.branch_id, organization_id=membership.organization_id, is_active=True).first():
        raise HTTPException(404, "Branch not found")
    row = Record(organization_id=membership.organization_id, module_key=module_key, record_type=payload.record_type,
                 data=payload.data, branch_id=payload.branch_id, created_by=user.id)
    db.add(row); db.commit(); db.refresh(row)
    audit(db, user.id, membership.organization_id, "record.created", module_key, row.id)
    return {"id": row.id, "module_key": row.module_key, "record_type": row.record_type,
            "data": row.data, "branch_id": row.branch_id}

@router.put("/records/{module_key}/{record_id}")
def update_record(module_key: str, record_id: int, payload: RecordIn,
                  membership=Depends(active_membership), user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    validate_module_key(module_key)
    require_permission(membership, "update")
    row = db.query(Record).filter_by(id=record_id, organization_id=membership.organization_id,
                                     module_key=module_key).first()
    if not row:
        raise HTTPException(404, "Record not found")
    if not can_access_branch(membership, row.branch_id) or not can_access_branch(membership, payload.branch_id):
        raise HTTPException(404, "Record not found")
    if payload.branch_id is not None and not db.query(Branch).filter_by(id=payload.branch_id, organization_id=membership.organization_id, is_active=True).first():
        raise HTTPException(404, "Branch not found")
    row.record_type = payload.record_type
    row.data = payload.data
    row.branch_id = payload.branch_id
    db.commit(); db.refresh(row)
    audit(db, user.id, membership.organization_id, "record.updated", module_key, row.id)
    return {"id": row.id, "module_key": row.module_key, "record_type": row.record_type,
            "data": row.data, "branch_id": row.branch_id}

@router.delete("/records/{module_key}/{record_id}", status_code=204)
def delete_record(module_key: str, record_id: int, membership=Depends(active_membership),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    validate_module_key(module_key)
    require_permission(membership, "delete")
    row = db.query(Record).filter_by(id=record_id, organization_id=membership.organization_id,
                                     module_key=module_key).first()
    if not row or not can_access_branch(membership, row.branch_id):
        raise HTTPException(404, "Record not found")
    resource_id = row.id
    db.delete(row); db.commit()
    audit(db, user.id, membership.organization_id, "record.deleted", module_key, resource_id)

@router.get("/operations/audit")
def audit_log(membership=Depends(active_membership), db: Session = Depends(get_db),
              limit: int = Query(default=100, ge=1, le=500)):
    require_permission(membership, "read")
    rows = db.query(AuditEvent).filter_by(organization_id=membership.organization_id).order_by(
        AuditEvent.id.desc()).limit(limit).all()
    return [{"id": x.id, "actor_user_id": x.actor_user_id, "action": x.action, "resource_type": x.resource_type,
             "resource_id": x.resource_id, "detail": x.detail, "created_at": x.created_at.isoformat()} for x in rows]

@router.get("/admin/overview")
def admin_overview(user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return {"organizations": db.query(Organization).count(), "users": db.query(User).count(),
            "providers": public_provider_status()}


# Inventory is implemented as a tenant-owned product catalogue and append-only
# stock ledger. Stock changes are idempotent and branch-scoped; balances are
# derived from the ledger rather than stored as mutable counters.
@router.get("/inventory/products")
def inventory_products(membership=Depends(active_membership), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    rows = db.query(InventoryProduct).filter_by(
        organization_id=membership.organization_id, is_active=True
    ).order_by(InventoryProduct.name).all()
    return [{"id": p.id, "sku": p.sku, "name": p.name, "description": p.description,
             "unit": p.unit, "is_active": p.is_active} for p in rows]


@router.post("/inventory/products", status_code=201)
def create_inventory_product(payload: InventoryProductIn, membership=Depends(active_membership),
                             user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "create")
    sku = payload.sku.strip().upper()
    if db.query(InventoryProduct).filter_by(organization_id=membership.organization_id, sku=sku).first():
        raise HTTPException(409, "SKU already exists in this organization")
    row = InventoryProduct(organization_id=membership.organization_id, sku=sku,
                           name=payload.name.strip(), description=payload.description,
                           unit=payload.unit, created_by=user.id)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "SKU already exists in this organization")
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "inventory.product.created", "inventory_product", row.id)
    return {"id": row.id, "sku": row.sku, "name": row.name, "description": row.description,
            "unit": row.unit, "is_active": row.is_active}


@router.get("/inventory/stock")
def inventory_stock(product_id: int | None = Query(default=None, gt=0),
                    branch_id: str | None = None,
                    membership=Depends(active_membership), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    allowed = branch_scope_ids(membership)
    if branch_id and not can_access_branch(membership, branch_id):
        raise HTTPException(404, "Stock location not found")
    q = db.query(InventoryStockMovement.product_id, InventoryStockMovement.branch_id,
                 func.coalesce(func.sum(InventoryStockMovement.quantity_delta), 0).label("quantity"))
    q = q.filter(InventoryStockMovement.organization_id == membership.organization_id)
    if product_id is not None:
        q = q.filter(InventoryStockMovement.product_id == product_id)
    if branch_id is not None:
        q = q.filter(InventoryStockMovement.branch_id == branch_id)
    elif allowed is not None:
        if not allowed:
            return []
        q = q.filter(InventoryStockMovement.branch_id.in_(allowed))
    q = q.group_by(InventoryStockMovement.product_id, InventoryStockMovement.branch_id)
    rows = q.all()
    product_ids = {r.product_id for r in rows}
    products = {p.id: p for p in db.query(InventoryProduct).filter(
        InventoryProduct.organization_id == membership.organization_id,
        InventoryProduct.id.in_(product_ids) if product_ids else InventoryProduct.id == -1
    ).all()}
    return [{"product_id": r.product_id, "sku": products[r.product_id].sku,
             "name": products[r.product_id].name, "branch_id": r.branch_id,
             "quantity": str(r.quantity)} for r in rows if r.product_id in products]


@router.post("/inventory/movements", status_code=201)
def create_inventory_movement(payload: InventoryMovementIn, membership=Depends(active_membership),
                              user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "create")
    validate_stock_delta(payload.movement_type, payload.quantity_delta)
    if payload.branch_id:
        branch = db.query(Branch).filter_by(id=payload.branch_id,
            organization_id=membership.organization_id, is_active=True).first()
        if not branch or not can_access_branch(membership, branch.id):
            raise HTTPException(404, "Stock location not found")
    elif branch_scope_ids(membership) not in (None, []):
        raise HTTPException(422, "A branch-scoped user must select an authorized branch")
    elif branch_scope_ids(membership) == []:
        raise HTTPException(403, "No branch access is assigned")

    duplicate = db.query(InventoryStockMovement).filter_by(
        organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
    ).first()
    if duplicate:
        if (duplicate.product_id != payload.product_id or duplicate.branch_id != payload.branch_id
                or duplicate.quantity_delta != payload.quantity_delta
                or duplicate.movement_type != payload.movement_type):
            raise HTTPException(409, "Idempotency key was already used for a different movement")
        return {"id": duplicate.id, "status": "already_applied",
                "quantity_delta": str(duplicate.quantity_delta)}

    product = db.query(InventoryProduct).filter_by(
        id=payload.product_id, organization_id=membership.organization_id, is_active=True
    ).with_for_update().first()
    if not product:
        raise HTTPException(404, "Product not found")
    current = db.query(func.coalesce(func.sum(InventoryStockMovement.quantity_delta), 0)).filter(
        InventoryStockMovement.organization_id == membership.organization_id,
        InventoryStockMovement.product_id == product.id,
        InventoryStockMovement.branch_id == payload.branch_id
    ).scalar()
    new_balance = resulting_balance(Decimal(str(current or 0)), payload.quantity_delta)
    row = InventoryStockMovement(
        organization_id=membership.organization_id, product_id=product.id,
        branch_id=payload.branch_id, quantity_delta=payload.quantity_delta,
        movement_type=payload.movement_type, reference=payload.reference,
        idempotency_key=payload.idempotency_key, created_by=user.id
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = db.query(InventoryStockMovement).filter_by(
            organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
        ).first()
        if duplicate and duplicate.product_id == payload.product_id and duplicate.branch_id == payload.branch_id and duplicate.quantity_delta == payload.quantity_delta and duplicate.movement_type == payload.movement_type:
            return {"id": duplicate.id, "status": "already_applied",
                    "quantity_delta": str(duplicate.quantity_delta)}
        raise HTTPException(409, "Stock movement conflicts with an existing request")
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "inventory.stock.movement", "inventory_movement",
          row.id, f"{payload.movement_type}:{payload.quantity_delta}:{payload.branch_id or 'unassigned'}")
    return {"id": row.id, "status": "applied", "quantity_delta": str(row.quantity_delta),
            "balance": str(new_balance)}
