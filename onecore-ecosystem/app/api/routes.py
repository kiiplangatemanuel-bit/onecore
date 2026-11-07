import json, re, uuid
from decimal import Decimal
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import User, Organization, Membership, Branch, Record, AuditEvent, InventoryProduct, InventoryStockMovement, AccountingAccount, AccountingJournal, AccountingJournalLine, CRMContact, CRMLead, CRMActivity
from app.core.schemas import OrganizationIn, RecordIn, BranchIn, InventoryProductIn, InventoryMovementIn, AccountingAccountIn, AccountingJournalIn, CRMContactIn, CRMLeadIn, CRMLeadStageIn, CRMActivityIn
from app.core.security import current_user, verify_password, create_access_token, require_platform_admin
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, branch_scope_ids, can_access_branch
from app.integrations.registry import public_provider_status
from app.services.inventory import validate_stock_delta, resulting_balance
from app.services.accounting import validate_journal_lines
from app.services.crm import validate_stage_transition
from datetime import datetime, time, timezone

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
                or duplicate.movement_type != payload.movement_type or duplicate.reference != payload.reference):
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
        if duplicate and duplicate.product_id == payload.product_id and duplicate.branch_id == payload.branch_id and duplicate.quantity_delta == payload.quantity_delta and duplicate.movement_type == payload.movement_type and duplicate.reference == payload.reference:
            return {"id": duplicate.id, "status": "already_applied",
                    "quantity_delta": str(duplicate.quantity_delta)}
        raise HTTPException(409, "Stock movement conflicts with an existing request")
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "inventory.stock.movement", "inventory_movement",
          row.id, f"{payload.movement_type}:{payload.quantity_delta}:{payload.branch_id or 'unassigned'}")
    return {"id": row.id, "status": "applied", "quantity_delta": str(row.quantity_delta),
            "balance": str(new_balance)}


# Accounting foundation: tenant chart of accounts, posted double-entry journals,
# immutable posted lines and a tenant/branch-filtered trial balance.
@router.get("/accounting/accounts")
def accounting_accounts(membership=Depends(active_membership), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    rows = db.query(AccountingAccount).filter_by(
        organization_id=membership.organization_id, is_active=True
    ).order_by(AccountingAccount.code).all()
    return [{"id": a.id, "code": a.code, "name": a.name, "account_type": a.account_type}
            for a in rows]


@router.post("/accounting/accounts", status_code=201)
def create_accounting_account(payload: AccountingAccountIn,
                              membership=Depends(active_membership),
                              user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    code = payload.code.strip().upper()
    if db.query(AccountingAccount).filter_by(
        organization_id=membership.organization_id, code=code
    ).first():
        raise HTTPException(409, "Account code already exists in this organization")
    row = AccountingAccount(organization_id=membership.organization_id, code=code,
                            name=payload.name.strip(), account_type=payload.account_type,
                            created_by=user.id)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Account code already exists in this organization")
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "accounting.account.created",
          "accounting_account", row.id)
    return {"id": row.id, "code": row.code, "name": row.name, "account_type": row.account_type}


@router.post("/accounting/journals", status_code=201)
def post_accounting_journal(payload: AccountingJournalIn,
                            membership=Depends(active_membership),
                            user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "create")
    validate_journal_lines(payload.lines)
    allowed = branch_scope_ids(membership)
    branch_ids = {line.branch_id for line in payload.lines if line.branch_id}
    if payload.branch_id:
        branch_ids.add(payload.branch_id)
    if allowed is not None and (not allowed or any(b not in allowed for b in branch_ids)):
        raise HTTPException(403, "Journal contains a branch outside your membership scope")
    if branch_ids:
        valid = {b.id for b in db.query(Branch).filter(
            Branch.organization_id == membership.organization_id,
            Branch.is_active == True, Branch.id.in_(branch_ids)
        ).all()}
        if valid != branch_ids:
            raise HTTPException(404, "Journal branch not found")
    account_ids = {line.account_id for line in payload.lines}
    accounts = db.query(AccountingAccount).filter(
        AccountingAccount.organization_id == membership.organization_id,
        AccountingAccount.is_active == True,
        AccountingAccount.id.in_(account_ids)
    ).all()
    if {a.id for a in accounts} != account_ids:
        raise HTTPException(404, "Journal account not found")
    journal = AccountingJournal(
        organization_id=membership.organization_id, branch_id=payload.branch_id,
        journal_number="JRN-" + uuid.uuid4().hex[:16].upper(),
        reference=payload.reference, memo=payload.memo, status="posted",
        entry_date=datetime.combine(payload.entry_date, time.min, tzinfo=timezone.utc),
        created_by=user.id, posted_by=user.id, posted_at=datetime.now(timezone.utc)
    )
    db.add(journal)
    db.flush()
    for line in payload.lines:
        db.add(AccountingJournalLine(
            organization_id=membership.organization_id, journal_id=journal.id,
            account_id=line.account_id, branch_id=line.branch_id or payload.branch_id,
            description=line.description, debit=line.debit, credit=line.credit
        ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Journal could not be posted due to a conflicting request")
    db.refresh(journal)
    audit(db, user.id, membership.organization_id, "accounting.journal.posted",
          "accounting_journal", journal.id, journal.journal_number)
    return {"id": journal.id, "journal_number": journal.journal_number,
            "status": journal.status, "entry_date": payload.entry_date.isoformat()}


@router.get("/accounting/journals")
def list_accounting_journals(membership=Depends(active_membership), db: Session = Depends(get_db),
                             limit: int = Query(default=100, ge=1, le=500)):
    require_permission(membership, "read")
    query = db.query(AccountingJournal).filter_by(
        organization_id=membership.organization_id, status="posted"
    )
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            return []
        query = query.filter((AccountingJournal.branch_id == None) |
                             (AccountingJournal.branch_id.in_(allowed)))
    rows = query.order_by(AccountingJournal.id.desc()).limit(limit).all()
    return [{"id": j.id, "journal_number": j.journal_number, "reference": j.reference,
             "memo": j.memo, "entry_date": j.entry_date.date().isoformat(),
             "status": j.status} for j in rows]


@router.get("/accounting/trial-balance")
def accounting_trial_balance(membership=Depends(active_membership), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    query = db.query(
        AccountingAccount.id, AccountingAccount.code, AccountingAccount.name,
        AccountingAccount.account_type,
        func.coalesce(func.sum(AccountingJournalLine.debit), 0).label("debit"),
        func.coalesce(func.sum(AccountingJournalLine.credit), 0).label("credit")
    ).outerjoin(AccountingJournalLine, (
        (AccountingJournalLine.account_id == AccountingAccount.id) &
        (AccountingJournalLine.organization_id == membership.organization_id)
    )).filter(AccountingAccount.organization_id == membership.organization_id,
              AccountingAccount.is_active == True)
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            return {"accounts": [], "total_debits": "0.00", "total_credits": "0.00"}
        query = query.filter((AccountingJournalLine.branch_id == None) |
                             (AccountingJournalLine.branch_id.in_(allowed)))
    rows = query.group_by(AccountingAccount.id).order_by(AccountingAccount.code).all()
    accounts = [{"account_id": r.id, "code": r.code, "name": r.name,
                 "account_type": r.account_type, "debits": str(r.debit),
                 "credits": str(r.credit)} for r in rows]
    total_debits = sum((Decimal(str(r.debit)) for r in rows), Decimal("0"))
    total_credits = sum((Decimal(str(r.credit)) for r in rows), Decimal("0"))
    return {"accounts": accounts, "total_debits": str(total_debits),
            "total_credits": str(total_credits), "balanced": total_debits == total_credits}


# CRM: tenant-scoped contacts, qualified pipeline and auditable activities.
def _crm_branch_check(db, membership, branch_id):
    if branch_id is None:
        if branch_scope_ids(membership) == []:
            raise HTTPException(403, "No branch access is assigned")
        return
    branch = db.query(Branch).filter_by(
        id=branch_id, organization_id=membership.organization_id, is_active=True
    ).first()
    if not branch or not can_access_branch(membership, branch_id):
        raise HTTPException(404, "Branch not found")


@router.get("/crm/contacts")
def list_crm_contacts(membership=Depends(active_membership), db: Session = Depends(get_db),
                      limit: int = Query(default=100, ge=1, le=500)):
    require_permission(membership, "read")
    q = db.query(CRMContact).filter_by(organization_id=membership.organization_id)
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            return []
        q = q.filter(CRMContact.branch_id.in_(allowed))
    rows = q.order_by(CRMContact.id.desc()).limit(limit).all()
    return [{"id": x.id, "full_name": x.full_name, "email": x.email, "phone": x.phone,
             "company": x.company, "branch_id": x.branch_id} for x in rows]


@router.post("/crm/contacts", status_code=201)
def create_crm_contact(payload: CRMContactIn, membership=Depends(active_membership),
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "create")
    _crm_branch_check(db, membership, payload.branch_id)
    email = str(payload.email).lower() if payload.email else None
    phone = payload.phone.strip() if payload.phone else None
    if email and db.query(CRMContact).filter_by(
        organization_id=membership.organization_id, email=email
    ).first():
        raise HTTPException(409, "A contact with this email already exists in this organization")
    if phone and db.query(CRMContact).filter_by(
        organization_id=membership.organization_id, phone=phone
    ).first():
        raise HTTPException(409, "A contact with this phone already exists in this organization")
    row = CRMContact(organization_id=membership.organization_id, branch_id=payload.branch_id,
                     full_name=payload.full_name.strip(), email=email, phone=phone,
                     company=payload.company, notes=payload.notes, created_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "crm.contact.created", "crm_contact", row.id)
    return {"id": row.id, "full_name": row.full_name, "email": row.email,
            "phone": row.phone, "company": row.company, "branch_id": row.branch_id}


@router.get("/crm/leads")
def list_crm_leads(stage: str | None = None, membership=Depends(active_membership),
                   db: Session = Depends(get_db), limit: int = Query(default=100, ge=1, le=500)):
    require_permission(membership, "read")
    q = db.query(CRMLead).filter_by(organization_id=membership.organization_id)
    if stage:
        if stage not in {"new", "qualified", "proposal", "negotiation", "won", "lost"}:
            raise HTTPException(422, "Invalid lead stage")
        q = q.filter(CRMLead.stage == stage)
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            return []
        q = q.filter(CRMLead.branch_id.in_(allowed))
    rows = q.order_by(CRMLead.id.desc()).limit(limit).all()
    return [{"id": x.id, "title": x.title, "contact_id": x.contact_id, "stage": x.stage,
             "source": x.source, "estimated_value": str(x.estimated_value),
             "currency": x.currency, "assigned_to": x.assigned_to, "next_step": x.next_step,
             "branch_id": x.branch_id} for x in rows]


@router.post("/crm/leads", status_code=201)
def create_crm_lead(payload: CRMLeadIn, membership=Depends(active_membership),
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "create")
    _crm_branch_check(db, membership, payload.branch_id)
    if payload.contact_id and not db.query(CRMContact).filter_by(
        id=payload.contact_id, organization_id=membership.organization_id
    ).first():
        raise HTTPException(404, "Contact not found")
    if payload.assigned_to and not db.query(Membership).filter_by(
        user_id=payload.assigned_to, organization_id=membership.organization_id, is_active=True
    ).first():
        raise HTTPException(404, "Assigned user is not an active organization member")
    row = CRMLead(organization_id=membership.organization_id, branch_id=payload.branch_id,
                  contact_id=payload.contact_id, title=payload.title.strip(), source=payload.source,
                  stage=payload.stage, estimated_value=payload.estimated_value,
                  currency=payload.currency, assigned_to=payload.assigned_to,
                  next_step=payload.next_step, created_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "crm.lead.created", "crm_lead", row.id)
    return {"id": row.id, "title": row.title, "stage": row.stage,
            "estimated_value": str(row.estimated_value), "currency": row.currency}


@router.patch("/crm/leads/{lead_id}/stage")
def update_crm_lead_stage(lead_id: int, payload: CRMLeadStageIn,
                          membership=Depends(active_membership), user: User = Depends(current_user),
                          db: Session = Depends(get_db)):
    require_permission(membership, "update")
    q = db.query(CRMLead).filter_by(id=lead_id, organization_id=membership.organization_id)
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        q = q.filter(CRMLead.branch_id.in_(allowed)) if allowed else q.filter(CRMLead.id == -1)
    row = q.first()
    if not row:
        raise HTTPException(404, "Lead not found")
    previous = row.stage
    validate_stage_transition(previous, payload.stage)
    row.stage = payload.stage
    row.next_step = payload.next_step
    db.commit()
    audit(db, user.id, membership.organization_id, "crm.lead.stage_changed",
          "crm_lead", row.id, f"{previous}->{row.stage}")
    return {"id": row.id, "stage": row.stage, "next_step": row.next_step}


@router.get("/crm/activities")
def list_crm_activities(membership=Depends(active_membership), db: Session = Depends(get_db),
                        limit: int = Query(default=100, ge=1, le=500)):
    require_permission(membership, "read")
    q = db.query(CRMActivity).filter_by(organization_id=membership.organization_id)
    rows = q.order_by(CRMActivity.id.desc()).limit(limit).all()
    return [{"id": x.id, "contact_id": x.contact_id, "lead_id": x.lead_id,
             "activity_type": x.activity_type, "subject": x.subject, "notes": x.notes,
             "due_at": x.due_at.isoformat() if x.due_at else None,
             "completed_at": x.completed_at.isoformat() if x.completed_at else None}
            for x in rows]


@router.post("/crm/activities", status_code=201)
def create_crm_activity(payload: CRMActivityIn, membership=Depends(active_membership),
                         user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "create")
    if bool(payload.contact_id) == bool(payload.lead_id):
        raise HTTPException(422, "Specify exactly one contact or lead")
    if payload.contact_id and not db.query(CRMContact).filter_by(
        id=payload.contact_id, organization_id=membership.organization_id
    ).first():
        raise HTTPException(404, "Contact not found")
    if payload.lead_id and not db.query(CRMLead).filter_by(
        id=payload.lead_id, organization_id=membership.organization_id
    ).first():
        raise HTTPException(404, "Lead not found")
    row = CRMActivity(organization_id=membership.organization_id,
                      contact_id=payload.contact_id, lead_id=payload.lead_id,
                      activity_type=payload.activity_type, subject=payload.subject.strip(),
                      notes=payload.notes, due_at=payload.due_at, created_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "crm.activity.created",
          "crm_activity", row.id)
    return {"id": row.id, "activity_type": row.activity_type, "subject": row.subject}


@router.post("/crm/activities/{activity_id}/complete")
def complete_crm_activity(activity_id: int, membership=Depends(active_membership),
                          user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "update")
    row = db.query(CRMActivity).filter_by(
        id=activity_id, organization_id=membership.organization_id
    ).first()
    if not row:
        raise HTTPException(404, "Activity not found")
    if row.completed_at is None:
        row.completed_at = datetime.now(timezone.utc)
        db.commit()
        audit(db, user.id, membership.organization_id, "crm.activity.completed",
              "crm_activity", row.id)
    return {"id": row.id, "completed_at": row.completed_at.isoformat()}
