import json, re, uuid, hashlib
from decimal import Decimal
from sqlalchemy import func, and_, or_
from sqlalchemy.exc import IntegrityError
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import User, Organization, Membership, Branch, Record, AuditEvent, InventoryProduct, InventoryStockMovement, AccountingAccount, AccountingJournal, AccountingJournalLine, AccountingInvoice, AccountingInvoiceLine, AccountingInvoicePayment, CRMContact, CRMLead, CRMActivity, ProcurementSupplier, ProcurementPurchaseOrder, ProcurementPurchaseOrderLine, POSShift, POSSale, POSSaleLine, POSPayment, SchoolClass, SchoolLearner, SchoolSubject, SchoolAssessment, SchoolMark, SchoolGradeBand
from app.core.schemas import OrganizationIn, RecordIn, BranchIn, InventoryProductIn, InventoryMovementIn, AccountingAccountIn, AccountingJournalIn, AccountingInvoiceIn, AccountingInvoicePaymentIn, CRMContactIn, CRMLeadIn, CRMLeadStageIn, CRMActivityIn, ProcurementSupplierIn, PurchaseOrderIn, PurchaseOrderReceiptIn, POSShiftOpenIn, POSShiftCloseIn, POSSaleSyncIn, SchoolClassIn, SchoolLearnerIn, SchoolSubjectIn, SchoolAssessmentIn, SchoolMarksIn, SchoolGradeBandIn
from app.core.security import current_user, verify_password, create_access_token, require_platform_admin
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, branch_scope_ids, can_access_branch
from app.integrations.registry import public_provider_status
from app.services.inventory import validate_stock_delta, resulting_balance
from app.services.accounting import validate_journal_lines
from app.services.crm import validate_stage_transition
from app.services.pos import money, validate_payment_total, canonical_request_hash
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
             "unit": p.unit, "sale_price": str(p.sale_price), "is_active": p.is_active} for p in rows]


@router.post("/inventory/products", status_code=201)
def create_inventory_product(payload: InventoryProductIn, membership=Depends(active_membership),
                             user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "create")
    sku = payload.sku.strip().upper()
    if db.query(InventoryProduct).filter_by(organization_id=membership.organization_id, sku=sku).first():
        raise HTTPException(409, "SKU already exists in this organization")
    row = InventoryProduct(organization_id=membership.organization_id, sku=sku,
                           name=payload.name.strip(), description=payload.description,
                           unit=payload.unit, sale_price=payload.sale_price, created_by=user.id)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "SKU already exists in this organization")
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "inventory.product.created", "inventory_product", row.id)
    return {"id": row.id, "sku": row.sku, "name": row.name, "description": row.description,
            "unit": row.unit, "sale_price": str(row.sale_price), "is_active": row.is_active}


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
    if payload.contact_id:
        contact = db.query(CRMContact).filter_by(
            id=payload.contact_id, organization_id=membership.organization_id
        ).first()
        if not contact or not can_access_branch(membership, contact.branch_id):
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
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            return []
        q = q.outerjoin(CRMContact, CRMActivity.contact_id == CRMContact.id).outerjoin(
            CRMLead, CRMActivity.lead_id == CRMLead.id
        ).filter(or_(
            and_(CRMActivity.contact_id.isnot(None), CRMContact.branch_id.in_(allowed)),
            and_(CRMActivity.lead_id.isnot(None), CRMLead.branch_id.in_(allowed))
        ))
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
    if payload.contact_id:
        contact = db.query(CRMContact).filter_by(
            id=payload.contact_id, organization_id=membership.organization_id
        ).first()
        if not contact or not can_access_branch(membership, contact.branch_id):
            raise HTTPException(404, "Contact not found")
    if payload.lead_id:
        lead = db.query(CRMLead).filter_by(
            id=payload.lead_id, organization_id=membership.organization_id
        ).first()
        if not lead or not can_access_branch(membership, lead.branch_id):
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
    if row.contact_id:
        contact = db.query(CRMContact).filter_by(
            id=row.contact_id, organization_id=membership.organization_id
        ).first()
        if not contact or not can_access_branch(membership, contact.branch_id):
            raise HTTPException(404, "Activity not found")
    if row.lead_id:
        lead = db.query(CRMLead).filter_by(
            id=row.lead_id, organization_id=membership.organization_id
        ).first()
        if not lead or not can_access_branch(membership, lead.branch_id):
            raise HTTPException(404, "Activity not found")
    if row.completed_at is None:
        row.completed_at = datetime.now(timezone.utc)
        db.commit()
        audit(db, user.id, membership.organization_id, "crm.activity.completed",
              "crm_activity", row.id)
    return {"id": row.id, "completed_at": row.completed_at.isoformat()}


# Procurement: supplier directory, controlled purchase order approval and
# idempotent goods receipt into the existing inventory movement ledger.
def _procurement_branch_check(db, membership, branch_id):
    if branch_id is None:
        if branch_scope_ids(membership) == []:
            raise HTTPException(403, "No branch access is assigned")
        return
    branch = db.query(Branch).filter_by(
        id=branch_id, organization_id=membership.organization_id, is_active=True
    ).first()
    if not branch or not can_access_branch(membership, branch_id):
        raise HTTPException(404, "Branch not found")


@router.get("/procurement/suppliers")
def list_procurement_suppliers(membership=Depends(active_membership), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    rows = db.query(ProcurementSupplier).filter_by(
        organization_id=membership.organization_id, is_active=True
    ).order_by(ProcurementSupplier.name).all()
    return [{"id": x.id, "name": x.name, "email": x.email, "phone": x.phone, "tax_pin": x.tax_pin}
            for x in rows]


@router.post("/procurement/suppliers", status_code=201)
def create_procurement_supplier(payload: ProcurementSupplierIn,
                                membership=Depends(active_membership),
                                user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "create")
    row = ProcurementSupplier(organization_id=membership.organization_id,
                              name=payload.name.strip(),
                              email=str(payload.email).lower() if payload.email else None,
                              phone=payload.phone.strip() if payload.phone else None,
                              tax_pin=payload.tax_pin.strip().upper(), created_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "procurement.supplier.created",
          "procurement_supplier", row.id)
    return {"id": row.id, "name": row.name, "email": row.email,
            "phone": row.phone, "tax_pin": row.tax_pin}


@router.get("/procurement/orders")
def list_purchase_orders(membership=Depends(active_membership), db: Session = Depends(get_db),
                         limit: int = Query(default=100, ge=1, le=500)):
    require_permission(membership, "read")
    q = db.query(ProcurementPurchaseOrder).filter_by(organization_id=membership.organization_id)
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            return []
        q = q.filter(ProcurementPurchaseOrder.branch_id.in_(allowed))
    rows = q.order_by(ProcurementPurchaseOrder.id.desc()).limit(limit).all()
    return [{"id": x.id, "order_number": x.order_number, "supplier_id": x.supplier_id,
             "branch_id": x.branch_id, "status": x.status, "currency": x.currency,
             "notes": x.notes} for x in rows]


@router.post("/procurement/orders", status_code=201)
def create_purchase_order(payload: PurchaseOrderIn, membership=Depends(active_membership),
                          user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "create")
    _procurement_branch_check(db, membership, payload.branch_id)
    supplier = db.query(ProcurementSupplier).filter_by(
        id=payload.supplier_id, organization_id=membership.organization_id, is_active=True
    ).first()
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    product_ids = {line.product_id for line in payload.lines}
    products = db.query(InventoryProduct).filter(
        InventoryProduct.organization_id == membership.organization_id,
        InventoryProduct.is_active == True, InventoryProduct.id.in_(product_ids)
    ).all()
    if {p.id for p in products} != product_ids:
        raise HTTPException(404, "One or more products were not found")
    order = ProcurementPurchaseOrder(
        organization_id=membership.organization_id, branch_id=payload.branch_id,
        supplier_id=supplier.id, order_number="PO-" + uuid.uuid4().hex[:14].upper(),
        status="draft", currency=payload.currency, notes=payload.notes, created_by=user.id
    )
    db.add(order)
    db.flush()
    for line in payload.lines:
        db.add(ProcurementPurchaseOrderLine(
            organization_id=membership.organization_id, purchase_order_id=order.id,
            product_id=line.product_id, quantity_ordered=line.quantity,
            quantity_received=Decimal("0"), unit_cost=line.unit_cost
        ))
    db.commit()
    db.refresh(order)
    audit(db, user.id, membership.organization_id, "procurement.order.created",
          "purchase_order", order.id, order.order_number)
    return {"id": order.id, "order_number": order.order_number, "status": order.status}


@router.post("/procurement/orders/{order_id}/approve")
def approve_purchase_order(order_id: int, membership=Depends(active_membership),
                           user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    q = db.query(ProcurementPurchaseOrder).filter_by(
        id=order_id, organization_id=membership.organization_id
    )
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        q = q.filter(ProcurementPurchaseOrder.branch_id.in_(allowed)) if allowed else q.filter(ProcurementPurchaseOrder.id == -1)
    order = q.with_for_update().first()
    if not order:
        raise HTTPException(404, "Purchase order not found")
    if order.status != "draft":
        raise HTTPException(409, "Only draft purchase orders can be approved")
    order.status = "approved"
    order.approved_by = user.id
    order.approved_at = datetime.now(timezone.utc)
    db.commit()
    audit(db, user.id, membership.organization_id, "procurement.order.approved",
          "purchase_order", order.id, order.order_number)
    return {"id": order.id, "order_number": order.order_number, "status": order.status}


@router.post("/procurement/orders/{order_id}/receive")
def receive_purchase_order(order_id: int, payload: PurchaseOrderReceiptIn,
                           membership=Depends(active_membership), user: User = Depends(current_user),
                           db: Session = Depends(get_db)):
    require_permission(membership, "create")
    q = db.query(ProcurementPurchaseOrder).filter_by(
        id=order_id, organization_id=membership.organization_id
    )
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        q = q.filter(ProcurementPurchaseOrder.branch_id.in_(allowed)) if allowed else q.filter(ProcurementPurchaseOrder.id == -1)
    order = q.with_for_update().first()
    if not order:
        raise HTTPException(404, "Purchase order not found")
    if order.status not in {"approved", "partially_received"}:
        raise HTTPException(409, "Purchase order must be approved before receiving goods")
    _procurement_branch_check(db, membership, order.branch_id)
    received_now = 0
    for item in payload.lines:
        line = db.query(ProcurementPurchaseOrderLine).filter_by(
            id=item.line_id, purchase_order_id=order.id,
            organization_id=membership.organization_id
        ).with_for_update().first()
        if not line:
            raise HTTPException(404, "Purchase order line not found")
        duplicate = db.query(InventoryStockMovement).filter_by(
            organization_id=membership.organization_id, idempotency_key=item.idempotency_key
        ).first()
        if duplicate:
            if (duplicate.product_id == line.product_id and duplicate.branch_id == order.branch_id
                    and duplicate.quantity_delta == item.quantity
                    and duplicate.movement_type == "receipt"
                    and duplicate.reference == order.order_number):
                continue
            raise HTTPException(409, "Receipt idempotency key was already used")
        if line.quantity_received + item.quantity > line.quantity_ordered:
            raise HTTPException(409, "Receipt exceeds the outstanding purchase order quantity")
        db.add(InventoryStockMovement(
            organization_id=membership.organization_id, product_id=line.product_id,
            branch_id=order.branch_id, quantity_delta=item.quantity,
            movement_type="receipt", reference=order.order_number,
            idempotency_key=item.idempotency_key, created_by=user.id
        ))
        line.quantity_received += item.quantity
        received_now += 1
    db.flush()
    all_lines = db.query(ProcurementPurchaseOrderLine).filter_by(
        purchase_order_id=order.id, organization_id=membership.organization_id
    ).all()
    order.status = "received" if all(
        x.quantity_received >= x.quantity_ordered for x in all_lines
    ) else "partially_received"
    db.commit()
    audit(db, user.id, membership.organization_id, "procurement.goods_received",
          "purchase_order", order.id, f"new_receipt_lines:{received_now}")
    return {"id": order.id, "order_number": order.order_number,
            "status": order.status, "new_receipt_lines": received_now}


@router.get("/procurement/orders/{order_id}")
def get_purchase_order(order_id: int, membership=Depends(active_membership), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    q = db.query(ProcurementPurchaseOrder).filter_by(
        id=order_id, organization_id=membership.organization_id
    )
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        q = q.filter(ProcurementPurchaseOrder.branch_id.in_(allowed)) if allowed else q.filter(ProcurementPurchaseOrder.id == -1)
    order = q.first()
    if not order:
        raise HTTPException(404, "Purchase order not found")
    lines = db.query(ProcurementPurchaseOrderLine).filter_by(
        purchase_order_id=order.id, organization_id=membership.organization_id
    ).order_by(ProcurementPurchaseOrderLine.id).all()
    return {"id": order.id, "order_number": order.order_number, "supplier_id": order.supplier_id,
            "branch_id": order.branch_id, "status": order.status, "currency": order.currency,
            "lines": [{"id": x.id, "product_id": x.product_id,
                       "quantity_ordered": str(x.quantity_ordered),
                       "quantity_received": str(x.quantity_received),
                       "outstanding": str(x.quantity_ordered - x.quantity_received),
                       "unit_cost": str(x.unit_cost)} for x in lines]}


# POS shift accountability and idempotent online/offline transaction synchronization.
@router.get("/pos/catalog")
def pos_catalog(branch_id: str, membership=Depends(active_membership), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    _crm_branch_check(db, membership, branch_id)
    products = db.query(InventoryProduct).filter_by(
        organization_id=membership.organization_id, is_active=True
    ).order_by(InventoryProduct.name).all()
    result = []
    for product in products:
        stock = db.query(func.coalesce(func.sum(InventoryStockMovement.quantity_delta), 0)).filter(
            InventoryStockMovement.organization_id == membership.organization_id,
            InventoryStockMovement.product_id == product.id,
            InventoryStockMovement.branch_id == branch_id
        ).scalar()
        result.append({"id": product.id, "sku": product.sku, "name": product.name,
                       "unit": product.unit, "sale_price": str(product.sale_price),
                       "available_quantity": str(stock or 0)})
    return result


@router.post("/pos/shifts/open", status_code=201)
def open_pos_shift(payload: POSShiftOpenIn, membership=Depends(active_membership),
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "create")
    _crm_branch_check(db, membership, payload.branch_id)
    existing = db.query(POSShift).filter_by(
        organization_id=membership.organization_id, branch_id=payload.branch_id,
        cashier_user_id=user.id, status="open"
    ).first()
    if existing:
        raise HTTPException(409, "You already have an open shift at this branch")
    shift = POSShift(organization_id=membership.organization_id, branch_id=payload.branch_id,
                     cashier_user_id=user.id, status="open", opening_cash=payload.opening_cash)
    db.add(shift)
    db.commit()
    db.refresh(shift)
    audit(db, user.id, membership.organization_id, "pos.shift.opened", "pos_shift", shift.id)
    return {"id": shift.id, "branch_id": shift.branch_id, "status": shift.status,
            "opening_cash": str(shift.opening_cash)}


@router.post("/pos/shifts/{shift_id}/close")
def close_pos_shift(shift_id: int, payload: POSShiftCloseIn,
                    membership=Depends(active_membership), user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    require_permission(membership, "update")
    shift = db.query(POSShift).filter_by(
        id=shift_id, organization_id=membership.organization_id,
        cashier_user_id=user.id, status="open"
    ).with_for_update().first()
    if not shift or not can_access_branch(membership, shift.branch_id):
        raise HTTPException(404, "Open shift not found")
    cash_sales = db.query(func.coalesce(func.sum(POSPayment.amount), 0)).join(
        POSSale, POSSale.id == POSPayment.sale_id
    ).filter(POSSale.organization_id == membership.organization_id,
             POSSale.shift_id == shift.id, POSPayment.method == "cash",
             POSPayment.status == "recorded").scalar()
    expected = Decimal(str(shift.opening_cash)) + Decimal(str(cash_sales or 0))
    shift.closing_cash = payload.closing_cash
    shift.status = "closed"
    shift.closed_at = datetime.now(timezone.utc)
    db.commit()
    variance = payload.closing_cash - expected
    audit(db, user.id, membership.organization_id, "pos.shift.closed",
          "pos_shift", shift.id, f"expected:{expected};counted:{payload.closing_cash};variance:{variance}")
    return {"id": shift.id, "status": shift.status, "expected_cash": str(expected),
            "closing_cash": str(payload.closing_cash), "variance": str(variance)}


@router.post("/pos/sync", status_code=201)
def sync_pos_sale(payload: POSSaleSyncIn, membership=Depends(active_membership),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "create")
    _crm_branch_check(db, membership, payload.branch_id)
    request_hash = canonical_request_hash(payload)
    existing = db.query(POSSale).filter_by(
        organization_id=membership.organization_id,
        client_transaction_id=payload.client_transaction_id
    ).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "Client transaction ID was already used for different sale data")
        return {"id": existing.id, "client_transaction_id": existing.client_transaction_id,
                "status": "already_synced", "total_amount": str(existing.total_amount)}
    shift = db.query(POSShift).filter_by(
        id=payload.shift_id, organization_id=membership.organization_id,
        branch_id=payload.branch_id, cashier_user_id=user.id, status="open"
    ).with_for_update().first()
    if not shift:
        raise HTTPException(409, "An open cashier shift for this branch is required to sync sales")
    product_ids = {line.product_id for line in payload.lines}
    products = db.query(InventoryProduct).filter(
        InventoryProduct.organization_id == membership.organization_id,
        InventoryProduct.is_active == True, InventoryProduct.id.in_(product_ids)
    ).with_for_update().all()
    product_map = {p.id: p for p in products}
    if set(product_map) != product_ids:
        raise HTTPException(404, "One or more POS products were not found")
    total = Decimal("0.00")
    prepared = []
    aggregate_qty = {}
    for line in payload.lines:
        product = product_map[line.product_id]
        unit_price = money(Decimal(str(product.sale_price)))
        line_total = money(unit_price * line.quantity)
        if line_total <= 0:
            raise HTTPException(409, f"Product {product.sku} has no configured sale price")
        total += line_total
        aggregate_qty[line.product_id] = aggregate_qty.get(line.product_id, Decimal("0")) + line.quantity
        prepared.append((line, unit_price, line_total))
    total = money(total)
    validate_payment_total(total, payload.payments)
    for product_id, quantity in aggregate_qty.items():
        stock = db.query(func.coalesce(func.sum(InventoryStockMovement.quantity_delta), 0)).filter(
            InventoryStockMovement.organization_id == membership.organization_id,
            InventoryStockMovement.product_id == product_id,
            InventoryStockMovement.branch_id == payload.branch_id
        ).scalar()
        if Decimal(str(stock or 0)) < quantity:
            raise HTTPException(409, f"Insufficient stock for product {product_map[product_id].sku}")
    sale = POSSale(
        organization_id=membership.organization_id, branch_id=payload.branch_id,
        shift_id=shift.id, cashier_user_id=user.id,
        client_transaction_id=payload.client_transaction_id, request_hash=request_hash,
        total_amount=total, currency=payload.currency, status="posted",
        offline_created_at=payload.offline_created_at
    )
    db.add(sale)
    db.flush()
    for index, (line, unit_price, line_total) in enumerate(prepared):
        db.add(POSSaleLine(organization_id=membership.organization_id, sale_id=sale.id,
                           product_id=line.product_id, quantity=line.quantity,
                           unit_price=unit_price, line_total=line_total))
        db.add(InventoryStockMovement(
            organization_id=membership.organization_id, product_id=line.product_id,
            branch_id=payload.branch_id, quantity_delta=-line.quantity,
            movement_type="issue", reference=payload.client_transaction_id,
            idempotency_key=f"pos:{hashlib.sha256(payload.client_transaction_id.encode()).hexdigest()[:32]}:{index}",
            created_by=user.id
        ))
    for payment in payload.payments:
        db.add(POSPayment(
            organization_id=membership.organization_id, sale_id=sale.id,
            method=payment.method, amount=money(payment.amount),
            provider_reference=payment.provider_reference,
            status="unsettled" if payment.method == "credit" else "recorded"
        ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(POSSale).filter_by(
            organization_id=membership.organization_id,
            client_transaction_id=payload.client_transaction_id
        ).first()
        if existing and existing.request_hash == request_hash:
            return {"id": existing.id, "client_transaction_id": existing.client_transaction_id,
                    "status": "already_synced", "total_amount": str(existing.total_amount)}
        raise HTTPException(409, "POS transaction conflicts with an existing synchronization")
    db.refresh(sale)
    audit(db, user.id, membership.organization_id, "pos.sale.synced",
          "pos_sale", sale.id, payload.client_transaction_id)
    return {"id": sale.id, "client_transaction_id": sale.client_transaction_id,
            "status": "synced", "total_amount": str(sale.total_amount), "currency": sale.currency}


@router.get("/pos/shifts/current")
def current_pos_shift(branch_id: str, membership=Depends(active_membership),
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    _crm_branch_check(db, membership, branch_id)
    shift = db.query(POSShift).filter_by(
        organization_id=membership.organization_id, branch_id=branch_id,
        cashier_user_id=user.id, status="open"
    ).first()
    if not shift:
        return None
    return {"id": shift.id, "branch_id": shift.branch_id, "status": shift.status,
            "opening_cash": str(shift.opening_cash), "opened_at": shift.opened_at.isoformat()}


# School foundation: admissions, CBC subject catalogue, assessments, grading and publication.
@router.get("/school/classes")
def school_classes(membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    rows=db.query(SchoolClass).filter_by(organization_id=membership.organization_id,is_active=True).all()
    return [{"id":x.id,"name":x.name,"stream":x.stream,"academic_year":x.academic_year,"branch_id":x.branch_id} for x in rows if can_access_branch(membership,x.branch_id)]


@router.post("/school/classes",status_code=201)
def create_school_class(payload:SchoolClassIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    if not can_access_branch(membership,payload.branch_id):
        raise HTTPException(403,"Branch access denied")
    _crm_branch_check(db,membership,payload.branch_id)
    row=SchoolClass(organization_id=membership.organization_id,branch_id=payload.branch_id,
        name=payload.name.strip(),stream=payload.stream.strip(),academic_year=payload.academic_year,created_by=user.id)
    db.add(row)
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Class and stream already exist for this academic year")
    db.refresh(row);audit(db,user.id,membership.organization_id,"school.class.created","school_class",row.id)
    return {"id":row.id,"name":row.name,"stream":row.stream,"academic_year":row.academic_year}


@router.get("/school/learners")
def school_learners(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    rows=db.query(SchoolLearner).filter_by(organization_id=membership.organization_id).order_by(SchoolLearner.admission_number).all()
    return [{"id":x.id,"admission_number":x.admission_number,"first_name":x.first_name,"last_name":x.last_name,
        "class_id":x.class_id,"branch_id":x.branch_id,"status":x.status} for x in rows if can_access_branch(membership,x.branch_id)]


@router.post("/school/admissions",status_code=201)
def create_school_admission(payload:SchoolLearnerIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    if not can_access_branch(membership,payload.branch_id): raise HTTPException(403,"Branch access denied")
    _crm_branch_check(db,membership,payload.branch_id)
    if payload.class_id:
        cls=db.query(SchoolClass).filter_by(id=payload.class_id,organization_id=membership.organization_id,is_active=True).first()
        if not cls or cls.branch_id != payload.branch_id: raise HTTPException(404,"Class not found in this branch")
    row=SchoolLearner(organization_id=membership.organization_id,branch_id=payload.branch_id,class_id=payload.class_id,
        admission_number=payload.admission_number.strip().upper(),first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),guardian_name=payload.guardian_name,guardian_phone=payload.guardian_phone,
        status="applicant",created_by=user.id)
    db.add(row)
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Admission number already exists")
    db.refresh(row);audit(db,user.id,membership.organization_id,"school.admission.created","school_learner",row.id)
    return {"id":row.id,"admission_number":row.admission_number,"status":row.status}


@router.post("/school/learners/{learner_id}/admit")
def admit_school_learner(learner_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(SchoolLearner).filter_by(id=learner_id,organization_id=membership.organization_id).with_for_update().first()
    if not row or not can_access_branch(membership,row.branch_id): raise HTTPException(404,"Learner not found")
    if row.status!="applicant": raise HTTPException(409,"Only applicants can be admitted")
    row.status="active";row.admitted_at=datetime.now(timezone.utc);db.commit()
    audit(db,user.id,membership.organization_id,"school.learner.admitted","school_learner",row.id)
    return {"id":row.id,"status":row.status}


@router.get("/school/subjects")
def school_subjects(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    rows=db.query(SchoolSubject).filter_by(organization_id=membership.organization_id,is_active=True).order_by(SchoolSubject.name).all()
    return [{"id":x.id,"code":x.code,"name":x.name} for x in rows]


@router.post("/school/subjects",status_code=201)
def create_school_subject(payload:SchoolSubjectIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    row=SchoolSubject(organization_id=membership.organization_id,code=payload.code.upper(),name=payload.name.strip(),created_by=user.id)
    db.add(row)
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Subject code already exists")
    db.refresh(row);audit(db,user.id,membership.organization_id,"school.subject.created","school_subject",row.id)
    return {"id":row.id,"code":row.code,"name":row.name}


@router.post("/school/assessments",status_code=201)
def create_school_assessment(payload:SchoolAssessmentIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    cls=db.query(SchoolClass).filter_by(id=payload.class_id,organization_id=membership.organization_id,is_active=True).first()
    subject=db.query(SchoolSubject).filter_by(id=payload.subject_id,organization_id=membership.organization_id,is_active=True).first()
    if not cls or not subject: raise HTTPException(404,"Class or subject not found")
    if not can_access_branch(membership,cls.branch_id): raise HTTPException(403,"Branch access denied")
    row=SchoolAssessment(organization_id=membership.organization_id,class_id=cls.id,subject_id=subject.id,
        title=payload.title,academic_year=payload.academic_year,term=payload.term,
        maximum_score=payload.maximum_score,weight=payload.weight,created_by=user.id)
    db.add(row);db.commit();db.refresh(row)
    audit(db,user.id,membership.organization_id,"school.assessment.created","school_assessment",row.id)
    return {"id":row.id,"status":row.status,"maximum_score":str(row.maximum_score)}


@router.put("/school/assessments/{assessment_id}/marks")
def enter_school_marks(assessment_id:int,payload:SchoolMarksIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"update")
    assessment=db.query(SchoolAssessment).filter_by(id=assessment_id,organization_id=membership.organization_id).with_for_update().first()
    if not assessment: raise HTTPException(404,"Assessment not found")
    if assessment.status!="draft": raise HTTPException(409,"Published assessment marks are locked")
    cls=db.query(SchoolClass).filter_by(id=assessment.class_id,organization_id=membership.organization_id).first()
    if not cls or not can_access_branch(membership,cls.branch_id): raise HTTPException(404,"Assessment not found")
    learner_ids=[x.learner_id for x in payload.marks]
    if len(set(learner_ids))!=len(learner_ids): raise HTTPException(422,"A learner may appear only once in a mark submission")
    learners=db.query(SchoolLearner).filter(SchoolLearner.organization_id==membership.organization_id,
        SchoolLearner.class_id==cls.id,SchoolLearner.id.in_(learner_ids),SchoolLearner.status=="active").all()
    learner_map={x.id:x for x in learners}
    if set(learner_map)!=set(learner_ids): raise HTTPException(422,"All learners must be active members of this class")
    if any(x.score>assessment.maximum_score for x in payload.marks): raise HTTPException(422,"A mark exceeds the assessment maximum")
    for item in payload.marks:
        row=db.query(SchoolMark).filter_by(organization_id=membership.organization_id,assessment_id=assessment.id,learner_id=item.learner_id).first()
        if row: row.score=item.score;row.entered_by=user.id
        else: db.add(SchoolMark(organization_id=membership.organization_id,assessment_id=assessment.id,
            learner_id=item.learner_id,score=item.score,entered_by=user.id))
    db.commit();audit(db,user.id,membership.organization_id,"school.marks.saved","school_assessment",assessment.id,f"count:{len(payload.marks)}")
    return {"assessment_id":assessment.id,"saved":len(payload.marks)}


@router.post("/school/grade-bands",status_code=201)
def create_school_grade_band(payload:SchoolGradeBandIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    if payload.minimum_percent>=payload.maximum_percent: raise HTTPException(422,"Grade minimum must be below maximum")
    overlaps=db.query(SchoolGradeBand).filter(SchoolGradeBand.organization_id==membership.organization_id,
        SchoolGradeBand.scale_name==payload.scale_name,
        SchoolGradeBand.minimum_percent < payload.maximum_percent,
        SchoolGradeBand.maximum_percent > payload.minimum_percent).first()
    if overlaps: raise HTTPException(409,"Grade bands in a scale cannot overlap")
    row=SchoolGradeBand(organization_id=membership.organization_id,scale_name=payload.scale_name,
        grade=payload.grade,minimum_percent=payload.minimum_percent,maximum_percent=payload.maximum_percent,points=payload.points)
    db.add(row)
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Grade already exists in this scale")
    db.refresh(row);audit(db,user.id,membership.organization_id,"school.grade_band.created","school_grade_band",row.id)
    return {"id":row.id,"grade":row.grade,"scale_name":row.scale_name}


@router.post("/school/assessments/{assessment_id}/publish")
def publish_school_assessment(assessment_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    assessment=db.query(SchoolAssessment).filter_by(id=assessment_id,organization_id=membership.organization_id).with_for_update().first()
    if not assessment: raise HTTPException(404,"Assessment not found")
    if assessment.status!="draft": raise HTTPException(409,"Assessment is already published")
    cls=db.query(SchoolClass).filter_by(id=assessment.class_id,organization_id=membership.organization_id).first()
    if not cls or not can_access_branch(membership,cls.branch_id): raise HTTPException(404,"Assessment not found")
    count=db.query(SchoolMark).filter_by(organization_id=membership.organization_id,assessment_id=assessment.id).count()
    if count==0: raise HTTPException(409,"An assessment without marks cannot be published")
    assessment.status="published";assessment.published_by=user.id;assessment.published_at=datetime.now(timezone.utc)
    db.commit();audit(db,user.id,membership.organization_id,"school.assessment.published","school_assessment",assessment.id)
    return {"id":assessment.id,"status":assessment.status,"published_at":assessment.published_at.isoformat()}


@router.get("/school/assessments/{assessment_id}/results")
def school_assessment_results(assessment_id:int,scale_name:str="default",membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    assessment=db.query(SchoolAssessment).filter_by(id=assessment_id,organization_id=membership.organization_id,status="published").first()
    if not assessment: raise HTTPException(404,"Published assessment not found")
    cls=db.query(SchoolClass).filter_by(id=assessment.class_id,organization_id=membership.organization_id).first()
    if not cls or not can_access_branch(membership,cls.branch_id): raise HTTPException(404,"Published assessment not found")
    rows=db.query(SchoolLearner,SchoolMark).join(SchoolMark,SchoolMark.learner_id==SchoolLearner.id).filter(
        SchoolMark.organization_id==membership.organization_id,SchoolMark.assessment_id==assessment.id,
        SchoolLearner.organization_id==membership.organization_id).all()
    bands=db.query(SchoolGradeBand).filter_by(organization_id=membership.organization_id,scale_name=scale_name).all()
    results=[]
    for learner,mark in rows:
        percent=(Decimal(mark.score)/Decimal(assessment.maximum_score))*Decimal("100")
        band=next((b for b in bands if b.minimum_percent<=percent<=b.maximum_percent),None)
        results.append({"learner_id":learner.id,"admission_number":learner.admission_number,
            "learner":learner.first_name+" "+learner.last_name,"score":str(mark.score),
            "maximum_score":str(assessment.maximum_score),"percentage":str(percent.quantize(Decimal("0.01"))),
            "grade":band.grade if band else None,"points":str(band.points) if band else None})
    results.sort(key=lambda x:(-Decimal(x["percentage"]),x["admission_number"]))
    previous=None;rank=0
    for index,item in enumerate(results,1):
        score=Decimal(item["percentage"])
        if score!=previous: rank=index
        item["rank"]=rank;previous=score
    return {"assessment_id":assessment.id,"status":"published","results":results}


@router.get("/school/assessments")
def list_school_assessments(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    rows=db.query(SchoolAssessment).filter_by(organization_id=membership.organization_id).order_by(
        SchoolAssessment.academic_year.desc(),SchoolAssessment.id.desc()).all()
    result=[]
    for row in rows:
        cls=db.query(SchoolClass).filter_by(id=row.class_id,organization_id=membership.organization_id).first()
        if cls and can_access_branch(membership,cls.branch_id):
            result.append({"id":row.id,"class_id":row.class_id,"subject_id":row.subject_id,
                "title":row.title,"academic_year":row.academic_year,"term":row.term,
                "maximum_score":str(row.maximum_score),"weight":str(row.weight),"status":row.status})
    return result


@router.get("/school/classes/{class_id}/report-cards")
def school_report_cards(class_id:int,term:str,scale_name:str="default",
                        membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    cls=db.query(SchoolClass).filter_by(id=class_id,organization_id=membership.organization_id,is_active=True).first()
    if not cls or not can_access_branch(membership,cls.branch_id): raise HTTPException(404,"Class not found")
    assessments=db.query(SchoolAssessment).filter_by(
        organization_id=membership.organization_id,class_id=class_id,term=term,status="published").all()
    if not assessments: return {"class_id":class_id,"term":term,"report_cards":[]}
    assessment_ids=[a.id for a in assessments]
    rows=db.query(SchoolLearner,SchoolMark,SchoolAssessment,SchoolSubject).join(
        SchoolMark,SchoolMark.learner_id==SchoolLearner.id).join(
        SchoolAssessment,SchoolAssessment.id==SchoolMark.assessment_id).join(
        SchoolSubject,SchoolSubject.id==SchoolAssessment.subject_id).filter(
        SchoolLearner.organization_id==membership.organization_id,
        SchoolLearner.class_id==class_id,SchoolLearner.status=="active",
        SchoolMark.organization_id==membership.organization_id,
        SchoolAssessment.id.in_(assessment_ids)).all()
    by_learner={}
    for learner,mark,assessment,subject in rows:
        entry=by_learner.setdefault(learner.id,{"learner_id":learner.id,"admission_number":learner.admission_number,
            "learner":learner.first_name+" "+learner.last_name,"weighted_total":Decimal("0"),
            "weight_total":Decimal("0"),"subjects":[]})
        pct=Decimal(mark.score)/Decimal(assessment.maximum_score)*Decimal("100")
        weight=Decimal(assessment.weight)
        entry["weighted_total"]+=pct*weight;entry["weight_total"]+=weight
        entry["subjects"].append({"subject":subject.name,"assessment":assessment.title,
            "score":str(mark.score),"maximum_score":str(assessment.maximum_score),
            "percentage":str(pct.quantize(Decimal("0.01")))})
    bands=db.query(SchoolGradeBand).filter_by(organization_id=membership.organization_id,scale_name=scale_name).all()
    cards=[]
    for entry in by_learner.values():
        average=entry["weighted_total"]/entry["weight_total"] if entry["weight_total"] else Decimal("0")
        band=next((b for b in bands if b.minimum_percent<=average<=b.maximum_percent),None)
        cards.append({"learner_id":entry["learner_id"],"admission_number":entry["admission_number"],
            "learner":entry["learner"],"weighted_average":str(average.quantize(Decimal("0.01"))),
            "grade":band.grade if band else None,"points":str(band.points) if band else None,
            "subjects":entry["subjects"]})
    cards.sort(key=lambda x:(-Decimal(x["weighted_average"]),x["admission_number"]))
    previous=None;rank=0
    for index,card in enumerate(cards,1):
        score=Decimal(card["weighted_average"])
        if score!=previous:rank=index
        card["rank"]=rank;previous=score
    return {"class_id":class_id,"term":term,"academic_year":cls.academic_year,"report_cards":cards}


# Accounts receivable/payable: draft invoices, controlled posting and idempotent
# settlement journals. Tax rates are configured by the tenant; this is not an
# eTIMS or statutory tax engine.
def _accounting_get_accounts(db, organization_id, account_ids):
    rows=db.query(AccountingAccount).filter(
        AccountingAccount.organization_id==organization_id,
        AccountingAccount.is_active==True,
        AccountingAccount.id.in_(set(account_ids))
    ).all()
    mapped={x.id:x for x in rows}
    if set(mapped)!=set(account_ids):
        raise HTTPException(404,"One or more accounting accounts were not found")
    return mapped


def _accounting_make_journal(db, membership, user, entry_date, reference, memo, lines, branch_id=None):
    journal=AccountingJournal(
        organization_id=membership.organization_id,branch_id=branch_id,
        journal_number="JRN-"+uuid.uuid4().hex[:16].upper(),reference=reference,
        memo=memo,status="posted",
        entry_date=datetime.combine(entry_date,time.min,tzinfo=timezone.utc),
        created_by=user.id,posted_by=user.id,posted_at=datetime.now(timezone.utc))
    db.add(journal);db.flush()
    for line in lines:
        db.add(AccountingJournalLine(
            organization_id=membership.organization_id,journal_id=journal.id,
            account_id=line["account_id"],branch_id=line.get("branch_id",branch_id),
            description=line["description"],debit=line["debit"],credit=line["credit"]))
    return journal


@router.post("/accounting/invoices",status_code=201)
def create_accounting_invoice(payload:AccountingInvoiceIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    if payload.due_date<payload.issue_date: raise HTTPException(422,"Due date cannot precede issue date")
    organization=db.query(Organization).filter_by(id=membership.organization_id,is_active=True).first()
    if not organization or payload.currency!=organization.currency:
        raise HTTPException(422,"Invoice currency must match the organization base currency")
    if payload.invoice_type=="receivable" and (not payload.contact_id or payload.supplier_id):
        raise HTTPException(422,"A receivable invoice requires a customer contact only")
    if payload.invoice_type=="payable" and (not payload.supplier_id or payload.contact_id):
        raise HTTPException(422,"A payable invoice requires a supplier only")
    if payload.branch_id: _crm_branch_check(db,membership,payload.branch_id)
    control=_accounting_get_accounts(db,membership.organization_id,[payload.control_account_id])[payload.control_account_id]
    expected_control="asset" if payload.invoice_type=="receivable" else "liability"
    if control.account_type!=expected_control:
        raise HTTPException(422,f"{payload.invoice_type} control account must be {expected_control}")
    if payload.contact_id and not db.query(CRMContact).filter_by(
        id=payload.contact_id,organization_id=membership.organization_id).first():
        raise HTTPException(404,"Customer contact not found")
    if payload.supplier_id and not db.query(ProcurementSupplier).filter_by(
        id=payload.supplier_id,organization_id=membership.organization_id,is_active=True).first():
        raise HTTPException(404,"Supplier not found")
    account_ids={x.account_id for x in payload.lines}
    account_ids.update(x.tax_account_id for x in payload.lines if x.tax_account_id)
    accounts=_accounting_get_accounts(db,membership.organization_id,account_ids)
    subtotal=Decimal("0.00");tax_total=Decimal("0.00");computed=[]
    for item in payload.lines:
        expected_line=("revenue",) if payload.invoice_type=="receivable" else ("expense","asset")
        if accounts[item.account_id].account_type not in expected_line:
            raise HTTPException(422,"Invoice line account type is not valid for this invoice")
        if item.tax_rate>0:
            if not item.tax_account_id: raise HTTPException(422,"Tax account is required when tax rate is greater than zero")
            expected_tax="liability" if payload.invoice_type=="receivable" else "asset"
            if accounts[item.tax_account_id].account_type!=expected_tax:
                raise HTTPException(422,f"Tax account must be {expected_tax} for this invoice type")
        elif item.tax_account_id:
            raise HTTPException(422,"Tax account must be omitted when tax rate is zero")
        line_sub=(item.quantity*item.unit_price).quantize(Decimal("0.01"))
        line_tax=(line_sub*item.tax_rate/Decimal("100")).quantize(Decimal("0.01"))
        line_total=line_sub+line_tax
        subtotal+=line_sub;tax_total+=line_tax
        computed.append((item,line_sub,line_tax,line_total))
    total=subtotal+tax_total
    if total<=0: raise HTTPException(422,"Invoice total must be greater than zero")
    invoice=AccountingInvoice(
        organization_id=membership.organization_id,branch_id=payload.branch_id,
        invoice_type=payload.invoice_type,contact_id=payload.contact_id,supplier_id=payload.supplier_id,
        invoice_number=payload.invoice_number.strip().upper(),
        issue_date=datetime.combine(payload.issue_date,time.min,tzinfo=timezone.utc),
        due_date=datetime.combine(payload.due_date,time.min,tzinfo=timezone.utc),
        currency=payload.currency,control_account_id=control.id,subtotal=subtotal,
        tax_total=tax_total,total=total,amount_paid=Decimal("0"),status="draft",created_by=user.id)
    db.add(invoice);db.flush()
    for item,line_sub,line_tax,line_total in computed:
        db.add(AccountingInvoiceLine(
            organization_id=membership.organization_id,invoice_id=invoice.id,
            account_id=item.account_id,tax_account_id=item.tax_account_id,
            description=item.description.strip(),quantity=item.quantity,unit_price=item.unit_price,
            subtotal=line_sub,tax_rate=item.tax_rate,tax_amount=line_tax,total=line_total))
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Invoice number already exists in this organization")
    db.refresh(invoice)
    audit(db,user.id,membership.organization_id,"accounting.invoice.created","accounting_invoice",invoice.id)
    return {"id":invoice.id,"invoice_number":invoice.invoice_number,"invoice_type":invoice.invoice_type,
        "subtotal":str(invoice.subtotal),"tax_total":str(invoice.tax_total),"total":str(invoice.total),
        "amount_paid":str(invoice.amount_paid),"balance":str(invoice.total),"status":invoice.status}


@router.get("/accounting/invoices")
def list_accounting_invoices(invoice_type:str|None=None,status:str|None=None,
    membership=Depends(active_membership),db:Session=Depends(get_db),
    limit:int=Query(default=100,ge=1,le=500)):
    require_permission(membership,"read")
    q=db.query(AccountingInvoice).filter_by(organization_id=membership.organization_id)
    if invoice_type:
        if invoice_type not in ("receivable","payable"): raise HTTPException(422,"Invalid invoice type")
        q=q.filter(AccountingInvoice.invoice_type==invoice_type)
    if status:
        if status not in ("draft","posted","partially_paid","paid"): raise HTTPException(422,"Invalid invoice status")
        q=q.filter(AccountingInvoice.status==status)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:return []
        q=q.filter((AccountingInvoice.branch_id==None)|(AccountingInvoice.branch_id.in_(allowed)))
    rows=q.order_by(AccountingInvoice.due_date,AccountingInvoice.id.desc()).limit(limit).all()
    return [{"id":x.id,"invoice_number":x.invoice_number,"invoice_type":x.invoice_type,
        "contact_id":x.contact_id,"supplier_id":x.supplier_id,"issue_date":x.issue_date.date().isoformat(),
        "due_date":x.due_date.date().isoformat(),"currency":x.currency,"subtotal":str(x.subtotal),
        "tax_total":str(x.tax_total),"total":str(x.total),"amount_paid":str(x.amount_paid),
        "balance":str(x.total-x.amount_paid),"status":x.status,"branch_id":x.branch_id} for x in rows]


@router.post("/accounting/invoices/{invoice_id}/post")
def post_accounting_invoice(invoice_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    invoice=db.query(AccountingInvoice).filter_by(
        id=invoice_id,organization_id=membership.organization_id).with_for_update().first()
    if not invoice: raise HTTPException(404,"Invoice not found")
    if invoice.status!="draft": raise HTTPException(409,"Only draft invoices can be posted")
    if invoice.branch_id and not can_access_branch(membership,invoice.branch_id):
        raise HTTPException(404,"Invoice not found")
    items=db.query(AccountingInvoiceLine).filter_by(
        invoice_id=invoice.id,organization_id=membership.organization_id).all()
    if not items: raise HTTPException(409,"Invoice has no lines")
    lines=[]
    if invoice.invoice_type=="receivable":
        lines.append({"account_id":invoice.control_account_id,"description":"Accounts receivable "+invoice.invoice_number,
            "debit":invoice.total,"credit":Decimal("0")})
        for item in items:
            lines.append({"account_id":item.account_id,"description":item.description,
                "debit":Decimal("0"),"credit":item.subtotal})
            if item.tax_amount:
                lines.append({"account_id":item.tax_account_id,"description":"Output tax "+item.description,
                    "debit":Decimal("0"),"credit":item.tax_amount})
    else:
        lines.append({"account_id":invoice.control_account_id,"description":"Accounts payable "+invoice.invoice_number,
            "debit":Decimal("0"),"credit":invoice.total})
        for item in items:
            lines.append({"account_id":item.account_id,"description":item.description,
                "debit":item.subtotal,"credit":Decimal("0")})
            if item.tax_amount:
                lines.append({"account_id":item.tax_account_id,"description":"Input tax "+item.description,
                    "debit":item.tax_amount,"credit":Decimal("0")})
    validate_journal_lines([type("Line",(),line)() for line in lines])
    journal=_accounting_make_journal(db,membership,user,invoice.issue_date.date(),
        invoice.invoice_number,"Invoice posting "+invoice.invoice_number,lines,invoice.branch_id)
    invoice.status="posted";invoice.journal_id=journal.id;invoice.posted_by=user.id
    invoice.posted_at=datetime.now(timezone.utc)
    db.commit();audit(db,user.id,membership.organization_id,"accounting.invoice.posted","accounting_invoice",invoice.id)
    return {"id":invoice.id,"status":invoice.status,"journal_id":journal.id,"journal_number":journal.journal_number}


@router.post("/accounting/invoices/{invoice_id}/payments",status_code=201)
def record_accounting_invoice_payment(invoice_id:int,payload:AccountingInvoicePaymentIn,
    membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    invoice=db.query(AccountingInvoice).filter_by(
        id=invoice_id,organization_id=membership.organization_id).with_for_update().first()
    if not invoice: raise HTTPException(404,"Invoice not found")
    if invoice.status not in ("posted","partially_paid"): raise HTTPException(409,"Only posted invoices can be paid")
    if invoice.branch_id and not can_access_branch(membership,invoice.branch_id): raise HTTPException(404,"Invoice not found")
    duplicate=db.query(AccountingInvoicePayment).filter_by(
        organization_id=membership.organization_id,idempotency_key=payload.idempotency_key).first()
    if duplicate:
        if (duplicate.invoice_id==invoice.id and duplicate.amount==payload.amount
                and duplicate.payment_account_id==payload.payment_account_id
                and duplicate.reference==payload.reference
                and duplicate.payment_date.date()==payload.payment_date):
            return {"id":duplicate.id,"status":"already_applied","journal_id":duplicate.journal_id}
        raise HTTPException(409,"Payment idempotency key was already used")
    balance=Decimal(invoice.total)-Decimal(invoice.amount_paid)
    if payload.amount>balance: raise HTTPException(422,"Payment exceeds outstanding invoice balance")
    payment_account=_accounting_get_accounts(db,membership.organization_id,[payload.payment_account_id])[payload.payment_account_id]
    if payment_account.account_type!="asset": raise HTTPException(422,"Payment account must be an asset account")
    if invoice.invoice_type=="receivable":
        journal_lines=[
            {"account_id":payment_account.id,"description":"Receipt "+invoice.invoice_number,"debit":payload.amount,"credit":Decimal("0")},
            {"account_id":invoice.control_account_id,"description":"Settle receivable "+invoice.invoice_number,"debit":Decimal("0"),"credit":payload.amount}]
    else:
        journal_lines=[
            {"account_id":invoice.control_account_id,"description":"Settle payable "+invoice.invoice_number,"debit":payload.amount,"credit":Decimal("0")},
            {"account_id":payment_account.id,"description":"Supplier payment "+invoice.invoice_number,"debit":Decimal("0"),"credit":payload.amount}]
    journal=_accounting_make_journal(db,membership,user,payload.payment_date, payload.reference,
        "Invoice settlement "+invoice.invoice_number,journal_lines,invoice.branch_id)
    payment=AccountingInvoicePayment(
        organization_id=membership.organization_id,invoice_id=invoice.id,payment_account_id=payment_account.id,
        journal_id=journal.id,amount=payload.amount,
        payment_date=datetime.combine(payload.payment_date,time.min,tzinfo=timezone.utc),
        reference=payload.reference,idempotency_key=payload.idempotency_key,created_by=user.id)
    db.add(payment);invoice.amount_paid=Decimal(invoice.amount_paid)+payload.amount
    invoice.status="paid" if invoice.amount_paid==invoice.total else "partially_paid"
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Payment conflicts with an existing request")
    audit(db,user.id,membership.organization_id,"accounting.invoice.payment","accounting_invoice",invoice.id,
        f"{payload.amount}:{payload.reference}")
    return {"id":payment.id,"status":invoice.status,"amount_paid":str(invoice.amount_paid),
        "balance":str(invoice.total-invoice.amount_paid),"journal_id":journal.id}


@router.get("/accounting/aging")
def accounting_aging(invoice_type:str=Query(pattern=r"^(receivable|payable)$"),
    as_of:date|None=None,membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    cutoff=as_of or datetime.now(timezone.utc).date()
    q=db.query(AccountingInvoice).filter(
        AccountingInvoice.organization_id==membership.organization_id,
        AccountingInvoice.invoice_type==invoice_type,
        AccountingInvoice.status.in_(("posted","partially_paid")))
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:return {"invoice_type":invoice_type,"as_of":cutoff.isoformat(),"buckets":{},"invoices":[]}
        q=q.filter((AccountingInvoice.branch_id==None)|(AccountingInvoice.branch_id.in_(allowed)))
    rows=q.order_by(AccountingInvoice.due_date).all()
    buckets={"current":Decimal("0"),"1_30":Decimal("0"),"31_60":Decimal("0"),"61_90":Decimal("0"),"over_90":Decimal("0")}
    output=[]
    for x in rows:
        balance=Decimal(x.total)-Decimal(x.amount_paid)
        if balance<=0:continue
        days=(cutoff-x.due_date.date()).days
        key="current" if days<=0 else "1_30" if days<=30 else "31_60" if days<=60 else "61_90" if days<=90 else "over_90"
        buckets[key]+=balance
        output.append({"invoice_id":x.id,"invoice_number":x.invoice_number,"due_date":x.due_date.date().isoformat(),
            "days_overdue":max(days,0),"balance":str(balance),"bucket":key})
    return {"invoice_type":invoice_type,"as_of":cutoff.isoformat(),
        "buckets":{k:str(v) for k,v in buckets.items()},"invoices":output}
