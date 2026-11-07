import json, re, uuid, hashlib
from decimal import Decimal
from sqlalchemy import func, and_, or_
from sqlalchemy.exc import IntegrityError
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import User, Organization, Membership, Branch, Record, AuditEvent, InventoryProduct, InventoryStockMovement, AccountingAccount, AccountingJournal, AccountingJournalLine, AccountingInvoice, AccountingInvoiceLine, AccountingInvoicePayment, AccountingFiscalPeriod, AccountingBudget, AccountingBudgetLine, AccountingFixedAsset, AccountingDepreciationEntry, AccountingBankStatement, AccountingBankStatementLine, AccountingInvoiceApproval, AccountingCreditNote, AccountingCreditNoteLine, CRMContact, CRMLead, CRMActivity, CRMQuote, CRMQuoteLine, CRMSalesOrder, CRMSalesOrderLine, CRMContactConsent, CRMCampaign, CRMCampaignRecipient, CRMCampaignAttribution, ProcurementSupplier, ProcurementPurchaseOrder, ProcurementPurchaseOrderLine, ProcurementRequisition, ProcurementRequisitionLine, ProcurementGoodsReceipt, ProcurementGoodsReceiptLine, ProcurementApprovalRule, ProcurementApprovalAction, ProcurementRFQ, ProcurementRFQLine, ProcurementRFQInvitation, ProcurementRFQQuote, ProcurementRFQQuoteLine, ProcurementSupplierInvoice, ProcurementSupplierInvoiceLine, ProcurementSupplierReturn, ProcurementSupplierReturnLine, POSShift, POSCashMovement, POSSale, POSSaleLine, POSPayment, POSReturn, POSReturnLine, POSRefund, SchoolClass, SchoolLearner, SchoolSubject, SchoolAssessment, SchoolMark, SchoolGradeBand, SchoolAttendance, SchoolEnrollmentHistory
from app.core.schemas import OrganizationIn, RecordIn, BranchIn, InventoryProductIn, InventoryProductTaxRateIn, InventoryMovementIn, AccountingAccountIn, AccountingJournalIn, AccountingInvoiceIn, AccountingInvoicePaymentIn, AccountingFiscalPeriodIn, AccountingBudgetIn, AccountingFixedAssetIn, AccountingDepreciationIn, AccountingBankStatementIn, AccountingBankMatchIn, AccountingInvoiceApprovalDecisionIn, AccountingCreditNoteIn, CRMContactIn, CRMLeadIn, CRMLeadStageIn, CRMActivityIn, CRMQuoteIn, CRMQuoteConvertIn, CRMContactConsentIn, CRMCampaignIn, ProcurementSupplierIn, PurchaseOrderIn, PurchaseOrderReceiptIn, ProcurementRequisitionIn, ProcurementRequisitionReviewIn, GoodsReceiptIn, GoodsReceiptInspectionIn, RequisitionConvertIn, ProcurementApprovalRuleIn, ProcurementRFQIn, ProcurementRFQQuoteIn, SupplierInvoiceIn, SupplierReturnIn, POSShiftOpenIn, POSShiftCloseIn, POSCashMovementIn, POSShiftReviewIn, POSSaleSyncIn, POSReturnIn, SchoolClassIn, SchoolLearnerIn, SchoolSubjectIn, SchoolAssessmentIn, SchoolMarksIn, SchoolGradeBandIn, SchoolAttendanceIn, SchoolLearnerPlacementIn
from app.core.security import current_user, verify_password, create_access_token, require_platform_admin
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, branch_scope_ids, can_access_branch
from app.integrations.registry import public_provider_status
from app.services.inventory import validate_stock_delta, resulting_balance
from app.services.accounting import validate_journal_lines
from app.services.crm import validate_stage_transition
from app.services.pos import money, calculate_pos_line, validate_payment_total, canonical_request_hash, canonical_return_hash, validate_return_refund_total
from datetime import date, datetime, time, timezone

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
             "unit": p.unit, "sale_price": str(p.sale_price),
             "tax_rate": str(p.tax_rate), "is_active": p.is_active} for p in rows]


@router.post("/inventory/products", status_code=201)
def create_inventory_product(payload: InventoryProductIn, membership=Depends(active_membership),
                             user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "manage" if payload.tax_rate > 0 else "create")
    sku = payload.sku.strip().upper()
    if db.query(InventoryProduct).filter_by(organization_id=membership.organization_id, sku=sku).first():
        raise HTTPException(409, "SKU already exists in this organization")
    row = InventoryProduct(organization_id=membership.organization_id, sku=sku,
                           name=payload.name.strip(), description=payload.description,
                           unit=payload.unit, sale_price=payload.sale_price,
                           tax_rate=payload.tax_rate, created_by=user.id)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "SKU already exists in this organization")
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "inventory.product.created", "inventory_product", row.id)
    return {"id": row.id, "sku": row.sku, "name": row.name, "description": row.description,
            "unit": row.unit, "sale_price": str(row.sale_price),
            "tax_rate": str(row.tax_rate), "is_active": row.is_active}


@router.patch("/inventory/products/{product_id}/tax-rate")
def update_inventory_product_tax_rate(product_id: int, payload: InventoryProductTaxRateIn,
                                      membership=Depends(active_membership),
                                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    product = db.query(InventoryProduct).filter_by(
        id=product_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not product:
        raise HTTPException(404, "Inventory product not found")
    previous_rate = Decimal(str(product.tax_rate))
    product.tax_rate = payload.tax_rate
    db.commit()
    audit(db, user.id, membership.organization_id, "inventory.product.tax_rate.updated",
          "inventory_product", product.id, f"previous:{previous_rate};new:{payload.tax_rate}")
    return {"id": product.id, "sku": product.sku, "tax_rate": str(product.tax_rate)}


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
    _accounting_assert_period_open(db,membership.organization_id,payload.entry_date)
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
             "company": x.company, "branch_id": x.branch_id, "expected_close_date": x.expected_close_date.isoformat() if x.expected_close_date else None,
             "probability_override": str(x.probability_override) if x.probability_override is not None else None,
             "actual_value": str(x.actual_value) if x.actual_value is not None else None,
             "source_campaign_id": x.source_campaign_id} for x in rows]


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
             "branch_id": x.branch_id, "expected_close_date": x.expected_close_date.isoformat() if x.expected_close_date else None,
             "probability_override": str(x.probability_override) if x.probability_override is not None else None,
             "actual_value": str(x.actual_value) if x.actual_value is not None else None,
             "source_campaign_id": x.source_campaign_id} for x in rows]


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
    row.actual_closed_at = datetime.now(timezone.utc) if payload.stage == "won" else None
    row.actual_value = row.estimated_value if payload.stage == "won" else None
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
    if (membership.role or "").lower() not in {"org_admin","manager"}:
        raise HTTPException(403,"Only procurement managers or organization administrators can approve purchase orders")
    q=db.query(ProcurementPurchaseOrder).filter_by(id=order_id,organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:q=q.filter(ProcurementPurchaseOrder.branch_id.in_(allowed)) if allowed else q.filter(ProcurementPurchaseOrder.id==-1)
    order=q.with_for_update().first()
    if not order:raise HTTPException(404,"Purchase order not found")
    if order.status!="draft":raise HTTPException(409,"Only draft purchase orders can be approved")
    if order.created_by==user.id:raise HTTPException(409,"Purchase order creator cannot approve their own order")
    lines=db.query(ProcurementPurchaseOrderLine).filter_by(purchase_order_id=order.id,organization_id=membership.organization_id).all()
    amount=sum((x.quantity_ordered*x.unit_cost for x in lines),Decimal("0"))
    rules=db.query(ProcurementApprovalRule).filter_by(organization_id=membership.organization_id,is_active=True).order_by(ProcurementApprovalRule.approval_level).all()
    required=[r for r in rules if amount>=r.minimum_amount and (r.maximum_amount is None or amount<r.maximum_amount)]
    if required:
        next_rule=None
        for rule in required:
            prior=db.query(ProcurementApprovalAction).filter_by(organization_id=membership.organization_id,
                entity_type="purchase_order",entity_id=order.id,approval_level=rule.approval_level).first()
            if not prior:next_rule=rule;break
        if next_rule is None:raise HTTPException(409,"All configured approval levels have already acted")
        if (membership.role or "").lower()!=next_rule.approver_role:
            raise HTTPException(403,"This approval level requires role: "+next_rule.approver_role)
        if db.query(ProcurementApprovalAction).filter_by(organization_id=membership.organization_id,
            entity_type="purchase_order",entity_id=order.id,approver_user_id=user.id).first():
            raise HTTPException(409,"A user may approve only one level of the same purchase order")
        action=ProcurementApprovalAction(organization_id=membership.organization_id,entity_type="purchase_order",
            entity_id=order.id,approval_level=next_rule.approval_level,approver_user_id=user.id,
            action="approved",note="")
        db.add(action);db.flush()
        completed=db.query(ProcurementApprovalAction).filter_by(organization_id=membership.organization_id,
            entity_type="purchase_order",entity_id=order.id,action="approved").count()
        if completed==len(required):
            order.status="approved";order.approved_by=user.id;order.approved_at=datetime.now(timezone.utc)
        audit(db,user.id,membership.organization_id,"procurement.order.approval_level_approved",
            "purchase_order",order.id,f"level:{next_rule.approval_level};amount:{amount}")
        db.commit()
        return {"id":order.id,"status":order.status,"amount":str(amount),
            "approval_level_completed":next_rule.approval_level,"approval_levels_required":len(required),
            "remaining_approvals":len(required)-completed}
    order.status="approved";order.approved_by=user.id;order.approved_at=datetime.now(timezone.utc)
    audit(db,user.id,membership.organization_id,"procurement.order.approved","purchase_order",order.id,order.order_number)
    db.commit()
    return {"id":order.id,"status":order.status,"amount":str(amount),"approval_levels_required":0}


@router.get("/procurement/orders/{order_id}/approvals")
def get_purchase_order_approvals(order_id:int,membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    order=db.query(ProcurementPurchaseOrder).filter_by(id=order_id,organization_id=membership.organization_id).first()
    if not order:raise HTTPException(404,"Purchase order not found")
    allowed=branch_scope_ids(membership)
    if allowed is not None and order.branch_id not in allowed:raise HTTPException(404,"Purchase order not found")
    actions=db.query(ProcurementApprovalAction).filter_by(organization_id=membership.organization_id,
        entity_type="purchase_order",entity_id=order.id).order_by(ProcurementApprovalAction.approval_level).all()
    return [{"level":x.approval_level,"approver_user_id":x.approver_user_id,"action":x.action,
        "note":x.note,"created_at":x.created_at.isoformat()} for x in actions]


@router.post("/procurement/orders/{order_id}/receive", deprecated=True)
def receive_purchase_order_legacy(order_id: int, payload: PurchaseOrderReceiptIn,
    membership=Depends(active_membership), db: Session=Depends(get_db)):
    """Legacy direct-to-stock receiving is disabled; use GRN inspection."""
    raise HTTPException(410, "Direct receiving is retired. Create a goods receipt and complete inspection instead.")


@router.post("/procurement/orders/{order_id}/goods-receipts", status_code=201)
def create_goods_receipt(order_id: int, payload: GoodsReceiptIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "create")
    q=db.query(ProcurementPurchaseOrder).filter_by(
        id=order_id, organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        q=q.filter(ProcurementPurchaseOrder.branch_id.in_(allowed)) if allowed else q.filter(ProcurementPurchaseOrder.id==-1)
    order=q.with_for_update().first()
    if not order:
        raise HTTPException(404,"Purchase order not found")
    if order.status not in {"approved","partially_received"}:
        raise HTTPException(409,"Only approved purchase orders can receive goods")
    _procurement_branch_check(db,membership,order.branch_id)
    receipt=ProcurementGoodsReceipt(
        organization_id=membership.organization_id,purchase_order_id=order.id,
        branch_id=order.branch_id,receipt_number="GRN-"+uuid.uuid4().hex[:14].upper(),
        status="pending_inspection",received_by=user.id)
    db.add(receipt)
    db.flush()
    try:
        for item in payload.lines:
            line=db.query(ProcurementPurchaseOrderLine).filter_by(
                id=item.line_id,purchase_order_id=order.id,
                organization_id=membership.organization_id).with_for_update().first()
            if not line:
                raise HTTPException(404,"Purchase order line not found")
            duplicate=db.query(ProcurementGoodsReceiptLine).filter_by(
                organization_id=membership.organization_id,
                idempotency_key=item.idempotency_key).first()
            if duplicate:
                raise HTTPException(409,"Receipt idempotency key has already been used")
            if line.quantity_received+item.quantity>line.quantity_ordered:
                raise HTTPException(409,"Receipt exceeds outstanding ordered quantity")
            db.add(ProcurementGoodsReceiptLine(
                organization_id=membership.organization_id,goods_receipt_id=receipt.id,
                purchase_order_line_id=line.id,product_id=line.product_id,
                quantity_received=item.quantity,quantity_accepted=Decimal("0"),
                quantity_rejected=Decimal("0"),idempotency_key=item.idempotency_key))
            line.quantity_received+=item.quantity
        all_lines=db.query(ProcurementPurchaseOrderLine).filter_by(
            purchase_order_id=order.id,organization_id=membership.organization_id).all()
        order.status="received" if all(x.quantity_received>=x.quantity_ordered for x in all_lines) else "partially_received"
        db.flush()
        audit(db,user.id,membership.organization_id,"procurement.grn.created",
            "goods_receipt",receipt.id,receipt.receipt_number)
        db.commit()
    except Exception:
        db.rollback()
        raise
    saved=db.query(ProcurementGoodsReceiptLine).filter_by(
        goods_receipt_id=receipt.id,organization_id=membership.organization_id).all()
    return {"id":receipt.id,"receipt_number":receipt.receipt_number,
        "status":receipt.status,"purchase_order_id":order.id,
        "lines":[{"id":x.id,"purchase_order_line_id":x.purchase_order_line_id,
        "quantity_received":str(x.quantity_received)} for x in saved]}


@router.get("/procurement/goods-receipts")
def list_goods_receipts(membership=Depends(active_membership),db:Session=Depends(get_db),
    limit:int=Query(default=100,ge=1,le=500)):
    require_permission(membership,"read")
    q=db.query(ProcurementGoodsReceipt).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        q=q.filter(ProcurementGoodsReceipt.branch_id.in_(allowed)) if allowed else q.filter(ProcurementGoodsReceipt.id==-1)
    rows=q.order_by(ProcurementGoodsReceipt.id.desc()).limit(limit).all()
    return [{"id":x.id,"receipt_number":x.receipt_number,"purchase_order_id":x.purchase_order_id,
        "status":x.status,"inspection_note":x.inspection_note,
        "created_at":x.created_at.isoformat()} for x in rows]


@router.get("/procurement/goods-receipts/{receipt_id}")
def get_goods_receipt(receipt_id:int,membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    q=db.query(ProcurementGoodsReceipt).filter_by(
        id=receipt_id,organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        q=q.filter(ProcurementGoodsReceipt.branch_id.in_(allowed)) if allowed else q.filter(ProcurementGoodsReceipt.id==-1)
    receipt=q.first()
    if not receipt:
        raise HTTPException(404,"Goods receipt not found")
    lines=db.query(ProcurementGoodsReceiptLine).filter_by(
        goods_receipt_id=receipt.id,organization_id=membership.organization_id).all()
    return {"id":receipt.id,"receipt_number":receipt.receipt_number,
        "purchase_order_id":receipt.purchase_order_id,"status":receipt.status,
        "inspection_note":receipt.inspection_note,
        "lines":[{"id":x.id,"purchase_order_line_id":x.purchase_order_line_id,
        "product_id":x.product_id,"quantity_received":str(x.quantity_received),
        "quantity_accepted":str(x.quantity_accepted),"quantity_rejected":str(x.quantity_rejected),
        "rejection_reason":x.rejection_reason} for x in lines]}


@router.post("/procurement/goods-receipts/{receipt_id}/inspect")
def inspect_goods_receipt(receipt_id:int,payload:GoodsReceiptInspectionIn,
    membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    q=db.query(ProcurementGoodsReceipt).filter_by(
        id=receipt_id,organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        q=q.filter(ProcurementGoodsReceipt.branch_id.in_(allowed)) if allowed else q.filter(ProcurementGoodsReceipt.id==-1)
    receipt=q.with_for_update().first()
    if not receipt:
        raise HTTPException(404,"Goods receipt not found")
    if receipt.status!="pending_inspection":
        raise HTTPException(409,"Only pending goods receipts can be inspected")
    _procurement_branch_check(db,membership,receipt.branch_id)
    lines={x.id:x for x in db.query(ProcurementGoodsReceiptLine).filter_by(
        goods_receipt_id=receipt.id,organization_id=membership.organization_id).with_for_update().all()}
    if {x.receipt_line_id for x in payload.lines}!=set(lines):
        raise HTTPException(422,"Inspection must account for every receipt line exactly once")
    try:
        for item in payload.lines:
            row=lines[item.receipt_line_id]
            if item.quantity_accepted+item.quantity_rejected!=row.quantity_received:
                raise HTTPException(422,"Accepted plus rejected quantity must equal received quantity")
            row.quantity_accepted=item.quantity_accepted
            row.quantity_rejected=item.quantity_rejected
            row.rejection_reason=item.rejection_reason.strip()
            if item.quantity_accepted>0:
                db.add(InventoryStockMovement(
                    organization_id=membership.organization_id,product_id=row.product_id,
                    branch_id=receipt.branch_id,quantity_delta=item.quantity_accepted,
                    movement_type="receipt",reference=receipt.receipt_number,
                    idempotency_key="grn-accepted-"+str(row.id),created_by=user.id))
        receipt.status="inspected"
        receipt.inspected_by=user.id
        receipt.inspected_at=datetime.now(timezone.utc)
        receipt.inspection_note=payload.note.strip()
        db.flush()
        audit(db,user.id,membership.organization_id,"procurement.grn.inspected",
            "goods_receipt",receipt.id,
            f"accepted:{sum((x.quantity_accepted for x in lines.values()),Decimal('0'))};rejected:{sum((x.quantity_rejected for x in lines.values()),Decimal('0'))}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"id":receipt.id,"receipt_number":receipt.receipt_number,
        "status":receipt.status,"accepted_quantity":str(sum((x.quantity_accepted for x in lines.values()),Decimal("0"))),
        "rejected_quantity":str(sum((x.quantity_rejected for x in lines.values()),Decimal("0")))}
 
 
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



# Purchase requisition workflow: draft -> submitted -> approved/rejected.
@router.get("/procurement/requisitions")
def list_procurement_requisitions(membership=Depends(active_membership),
    db: Session=Depends(get_db), limit:int=Query(default=100,ge=1,le=500)):
    require_permission(membership,"read")
    q=db.query(ProcurementRequisition).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        q=q.filter(ProcurementRequisition.branch_id.in_(allowed)) if allowed else q.filter(ProcurementRequisition.id==-1)
    rows=q.order_by(ProcurementRequisition.id.desc()).limit(limit).all()
    return [{"id":x.id,"requisition_number":x.requisition_number,"branch_id":x.branch_id,
        "status":x.status,"justification":x.justification,"requested_by":x.requested_by,
        "submitted_at":x.submitted_at.isoformat() if x.submitted_at else None,
        "reviewed_by":x.reviewed_by,"reviewed_at":x.reviewed_at.isoformat() if x.reviewed_at else None}
        for x in rows]


@router.post("/procurement/requisitions",status_code=201)
def create_procurement_requisition(payload:ProcurementRequisitionIn,
    membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    _procurement_branch_check(db,membership,payload.branch_id)
    ids={x.product_id for x in payload.lines}
    products=db.query(InventoryProduct).filter(
        InventoryProduct.organization_id==membership.organization_id,
        InventoryProduct.is_active==True,InventoryProduct.id.in_(ids)).all()
    if {x.id for x in products}!=ids:
        raise HTTPException(404,"One or more products were not found")
    row=ProcurementRequisition(organization_id=membership.organization_id,
        branch_id=payload.branch_id,requisition_number="REQ-"+uuid.uuid4().hex[:14].upper(),
        status="draft",justification=payload.justification.strip(),requested_by=user.id)
    db.add(row);db.flush()
    for item in payload.lines:
        db.add(ProcurementRequisitionLine(organization_id=membership.organization_id,
            requisition_id=row.id,product_id=item.product_id,quantity_requested=item.quantity))
    db.commit();db.refresh(row)
    audit(db,user.id,membership.organization_id,"procurement.requisition.created",
        "procurement_requisition",row.id,row.requisition_number)
    return {"id":row.id,"requisition_number":row.requisition_number,"status":row.status}


@router.get("/procurement/requisitions/{requisition_id}")
def get_procurement_requisition(requisition_id:int,membership=Depends(active_membership),
    db:Session=Depends(get_db)):
    require_permission(membership,"read")
    q=db.query(ProcurementRequisition).filter_by(id=requisition_id,
        organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        q=q.filter(ProcurementRequisition.branch_id.in_(allowed)) if allowed else q.filter(ProcurementRequisition.id==-1)
    row=q.first()
    if not row: raise HTTPException(404,"Requisition not found")
    lines=db.query(ProcurementRequisitionLine).filter_by(
        requisition_id=row.id,organization_id=membership.organization_id).order_by(
        ProcurementRequisitionLine.id).all()
    return {"id":row.id,"requisition_number":row.requisition_number,"branch_id":row.branch_id,
        "status":row.status,"justification":row.justification,"requested_by":row.requested_by,
        "reviewed_by":row.reviewed_by,"rejection_reason":row.rejection_reason,
        "lines":[{"id":x.id,"product_id":x.product_id,"quantity":str(x.quantity_requested)} for x in lines]}


@router.post("/procurement/requisitions/{requisition_id}/submit")
def submit_procurement_requisition(requisition_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    q=db.query(ProcurementRequisition).filter_by(id=requisition_id,
        organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        q=q.filter(ProcurementRequisition.branch_id.in_(allowed)) if allowed else q.filter(ProcurementRequisition.id==-1)
    row=q.with_for_update().first()
    if not row: raise HTTPException(404,"Requisition not found")
    if row.requested_by!=user.id: raise HTTPException(403,"Only the requester can submit this requisition")
    if row.status!="draft": raise HTTPException(409,"Only draft requisitions can be submitted")
    row.status="submitted";row.submitted_at=datetime.now(timezone.utc)
    db.commit()
    audit(db,user.id,membership.organization_id,"procurement.requisition.submitted",
        "procurement_requisition",row.id,row.requisition_number)
    return {"id":row.id,"status":row.status}


@router.post("/procurement/requisitions/{requisition_id}/approve")
def approve_procurement_requisition(requisition_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    q=db.query(ProcurementRequisition).filter_by(id=requisition_id,
        organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        q=q.filter(ProcurementRequisition.branch_id.in_(allowed)) if allowed else q.filter(ProcurementRequisition.id==-1)
    row=q.with_for_update().first()
    if not row: raise HTTPException(404,"Requisition not found")
    if row.status!="submitted": raise HTTPException(409,"Only submitted requisitions can be approved")
    if row.requested_by==user.id: raise HTTPException(409,"Requester cannot approve their own requisition")
    row.status="approved";row.reviewed_by=user.id;row.reviewed_at=datetime.now(timezone.utc)
    db.commit()
    audit(db,user.id,membership.organization_id,"procurement.requisition.approved",
        "procurement_requisition",row.id,row.requisition_number)
    return {"id":row.id,"status":row.status}


@router.post("/procurement/requisitions/{requisition_id}/reject")
def reject_procurement_requisition(requisition_id:int,payload:ProcurementRequisitionReviewIn,
    membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    if len(payload.reason.strip())<5: raise HTTPException(422,"A rejection reason of at least 5 characters is required")
    q=db.query(ProcurementRequisition).filter_by(id=requisition_id,
        organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        q=q.filter(ProcurementRequisition.branch_id.in_(allowed)) if allowed else q.filter(ProcurementRequisition.id==-1)
    row=q.with_for_update().first()
    if not row: raise HTTPException(404,"Requisition not found")
    if row.status!="submitted": raise HTTPException(409,"Only submitted requisitions can be rejected")
    if row.requested_by==user.id: raise HTTPException(409,"Requester cannot reject their own requisition")
    row.status="rejected";row.rejection_reason=payload.reason.strip()
    row.reviewed_by=user.id;row.reviewed_at=datetime.now(timezone.utc)
    db.commit()
    audit(db,user.id,membership.organization_id,"procurement.requisition.rejected",
        "procurement_requisition",row.id,payload.reason.strip())
    return {"id":row.id,"status":row.status}



# Approved requisitions convert to traceable purchase orders without re-keying products.
@router.post("/procurement/requisitions/{requisition_id}/convert-to-order", status_code=201)
def convert_requisition_to_order(requisition_id:int,payload:RequisitionConvertIn,
    membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    q=db.query(ProcurementRequisition).filter_by(id=requisition_id,organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:q=q.filter(ProcurementRequisition.branch_id.in_(allowed)) if allowed else q.filter(ProcurementRequisition.id==-1)
    req=q.with_for_update().first()
    if not req:raise HTTPException(404,"Requisition not found")
    if req.status!="approved":raise HTTPException(409,"Only approved requisitions can be converted")
    existing=db.query(ProcurementPurchaseOrder).filter(
        ProcurementPurchaseOrder.organization_id==membership.organization_id,
        ProcurementPurchaseOrder.notes.like("%requisition:"+str(req.id)+":%")).first()
    if existing:raise HTTPException(409,"This requisition has already been converted")
    supplier=db.query(ProcurementSupplier).filter_by(id=payload.supplier_id,organization_id=membership.organization_id,is_active=True).first()
    if not supplier:raise HTTPException(404,"Supplier not found")
    lines=db.query(ProcurementRequisitionLine).filter_by(requisition_id=req.id,organization_id=membership.organization_id).all()
    if not lines:raise HTTPException(409,"Requisition has no lines")
    if set(payload.unit_costs)-{x.product_id for x in lines}:raise HTTPException(422,"Unit costs contain products outside this requisition")
    order=ProcurementPurchaseOrder(organization_id=membership.organization_id,branch_id=req.branch_id,
        supplier_id=supplier.id,order_number="PO-"+uuid.uuid4().hex[:14].upper(),status="draft",
        currency=payload.currency,notes=(payload.notes+" [requisition:"+str(req.id)+":]").strip(),created_by=user.id)
    db.add(order);db.flush()
    for line in lines:
        db.add(ProcurementPurchaseOrderLine(organization_id=membership.organization_id,purchase_order_id=order.id,
            product_id=line.product_id,quantity_ordered=line.quantity_requested,quantity_received=Decimal("0"),
            unit_cost=payload.unit_costs.get(line.product_id,Decimal("0"))))
    audit(db,user.id,membership.organization_id,"procurement.requisition.converted","procurement_requisition",req.id,order.order_number)
    db.commit()
    return {"id":order.id,"order_number":order.order_number,"status":order.status,"requisition_id":req.id}


@router.put("/procurement/approval-rules")
def replace_procurement_approval_rules(payload:list[ProcurementApprovalRuleIn],
    membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    if len(payload)>5:raise HTTPException(422,"At most five approval levels are supported")
    levels=[x.approval_level for x in payload]
    if len(levels)!=len(set(levels)):raise HTTPException(422,"Approval levels must be unique")
    ordered=sorted(payload,key=lambda x:x.approval_level)
    db.query(ProcurementApprovalRule).filter_by(organization_id=membership.organization_id).delete()
    for rule in ordered:db.add(ProcurementApprovalRule(organization_id=membership.organization_id,**rule.model_dump(),created_by=user.id))
    audit(db,user.id,membership.organization_id,"procurement.approval_rules.updated","procurement_approval_rule",membership.organization_id)
    db.commit()
    return {"rules":[x.model_dump() for x in ordered]}


@router.get("/procurement/approval-rules")
def list_procurement_approval_rules(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    rows=db.query(ProcurementApprovalRule).filter_by(organization_id=membership.organization_id,is_active=True).order_by(ProcurementApprovalRule.approval_level).all()
    return [{"id":x.id,"minimum_amount":str(x.minimum_amount),"maximum_amount":str(x.maximum_amount) if x.maximum_amount is not None else None,"approval_level":x.approval_level,"approver_role":x.approver_role} for x in rows]


@router.post("/procurement/rfqs",status_code=201)
def create_procurement_rfq(payload:ProcurementRFQIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    _procurement_branch_check(db,membership,payload.branch_id)
    if payload.closing_date<=datetime.now(timezone.utc):raise HTTPException(422,"RFQ closing date must be in the future")
    suppliers=db.query(ProcurementSupplier).filter(ProcurementSupplier.organization_id==membership.organization_id,
        ProcurementSupplier.is_active==True,ProcurementSupplier.id.in_(payload.supplier_ids)).all()
    if {x.id for x in suppliers}!=set(payload.supplier_ids):raise HTTPException(404,"One or more suppliers not found")
    pids={x.product_id for x in payload.lines}
    products=db.query(InventoryProduct).filter(InventoryProduct.organization_id==membership.organization_id,
        InventoryProduct.is_active==True,InventoryProduct.id.in_(pids)).all()
    if {x.id for x in products}!=pids:raise HTTPException(404,"One or more products not found")
    row=ProcurementRFQ(organization_id=membership.organization_id,branch_id=payload.branch_id,
        rfq_number="RFQ-"+uuid.uuid4().hex[:14].upper(),status="open",closing_date=payload.closing_date,
        notes=payload.notes,created_by=user.id)
    db.add(row);db.flush()
    for x in payload.lines:db.add(ProcurementRFQLine(organization_id=membership.organization_id,rfq_id=row.id,product_id=x.product_id,quantity=x.quantity))
    for sid in payload.supplier_ids:db.add(ProcurementRFQInvitation(organization_id=membership.organization_id,rfq_id=row.id,supplier_id=sid))
    audit(db,user.id,membership.organization_id,"procurement.rfq.created","procurement_rfq",row.id,row.rfq_number)
    db.commit()
    return {"id":row.id,"rfq_number":row.rfq_number,"status":row.status,"invited_suppliers":len(suppliers)}


@router.post("/procurement/rfqs/{rfq_id}/quotes",status_code=201)
def submit_procurement_rfq_quote(rfq_id:int,payload:ProcurementRFQQuoteIn,
    membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    rfq=db.query(ProcurementRFQ).filter_by(id=rfq_id,organization_id=membership.organization_id).first()
    if not rfq:raise HTTPException(404,"RFQ not found")
    if rfq.status!="open" or rfq.closing_date.replace(tzinfo=timezone.utc)<datetime.now(timezone.utc):raise HTTPException(409,"RFQ is closed")
    invite=db.query(ProcurementRFQInvitation).filter_by(rfq_id=rfq.id,supplier_id=payload.supplier_id,organization_id=membership.organization_id).first()
    if not invite:raise HTTPException(403,"Supplier was not invited to this RFQ")
    if db.query(ProcurementRFQQuote).filter_by(rfq_id=rfq.id,supplier_id=payload.supplier_id).first():raise HTTPException(409,"Supplier quote already submitted")
    rfq_lines=db.query(ProcurementRFQLine).filter_by(rfq_id=rfq.id,organization_id=membership.organization_id).all()
    if {x.rfq_line_id for x in payload.lines}!={x.id for x in rfq_lines}:raise HTTPException(422,"Quote must price every RFQ line exactly once")
    quote=ProcurementRFQQuote(organization_id=membership.organization_id,rfq_id=rfq.id,supplier_id=payload.supplier_id,
        currency=payload.currency,delivery_days=payload.delivery_days,status="submitted",submitted_by=user.id)
    db.add(quote);db.flush()
    for x in payload.lines:db.add(ProcurementRFQQuoteLine(organization_id=membership.organization_id,quote_id=quote.id,rfq_line_id=x.rfq_line_id,unit_price=x.unit_price,tax_rate=x.tax_rate))
    invite.status="quoted"
    audit(db,user.id,membership.organization_id,"procurement.rfq.quote_submitted","procurement_rfq_quote",quote.id)
    db.commit()
    return {"id":quote.id,"status":quote.status}


@router.get("/procurement/rfqs/{rfq_id}/comparison")
def compare_procurement_rfq_quotes(rfq_id:int,membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    rfq=db.query(ProcurementRFQ).filter_by(id=rfq_id,organization_id=membership.organization_id).first()
    if not rfq:raise HTTPException(404,"RFQ not found")
    quotes=db.query(ProcurementRFQQuote).filter_by(rfq_id=rfq.id,organization_id=membership.organization_id).all()
    result=[]
    for q in quotes:
        supplier=db.query(ProcurementSupplier).filter_by(id=q.supplier_id,organization_id=membership.organization_id).first()
        lines=db.query(ProcurementRFQQuoteLine,ProcurementRFQLine).join(ProcurementRFQLine,ProcurementRFQQuoteLine.rfq_line_id==ProcurementRFQLine.id).filter(ProcurementRFQQuoteLine.quote_id==q.id).all()
        total=sum((line.quantity*quoted.unit_price*(Decimal("1")+quoted.tax_rate/Decimal("100")) for quoted,line in lines),Decimal("0"))
        result.append({"quote_id":q.id,"supplier_id":q.supplier_id,"supplier":supplier.name if supplier else "",
            "currency":q.currency,"delivery_days":q.delivery_days,"total":str(total),
            "lines":[{"product_id":line.product_id,"quantity":str(line.quantity),"unit_price":str(quoted.unit_price),"tax_rate":str(quoted.tax_rate)} for quoted,line in lines]})
    return sorted(result,key=lambda x:(x["currency"],Decimal(x["total"]),x["delivery_days"]))


@router.post("/procurement/rfqs/{rfq_id}/quotes/{quote_id}/award",status_code=201)
def award_procurement_quote(rfq_id:int,quote_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    rfq=db.query(ProcurementRFQ).filter_by(id=rfq_id,organization_id=membership.organization_id).first()
    quote=db.query(ProcurementRFQQuote).filter_by(id=quote_id,rfq_id=rfq_id,organization_id=membership.organization_id).first()
    if not rfq or not quote:raise HTTPException(404,"RFQ or quotation not found")
    if rfq.status!="open":raise HTTPException(409,"RFQ is not open")
    invitation=db.query(ProcurementRFQInvitation).filter_by(rfq_id=rfq.id,supplier_id=quote.supplier_id,organization_id=membership.organization_id).first()
    if not invitation:raise HTTPException(409,"Supplier invitation is missing")
    rfq_lines=db.query(ProcurementRFQLine).filter_by(rfq_id=rfq.id,organization_id=membership.organization_id).all()
    quote_lines=db.query(ProcurementRFQQuoteLine).filter_by(quote_id=quote.id,organization_id=membership.organization_id).all()
    if {x.rfq_line_id for x in quote_lines}!={x.id for x in rfq_lines}:raise HTTPException(409,"Quotation is incomplete")
    supplier=db.query(ProcurementSupplier).filter_by(id=quote.supplier_id,organization_id=membership.organization_id,is_active=True).first()
    order=ProcurementPurchaseOrder(organization_id=membership.organization_id,branch_id=rfq.branch_id,
        supplier_id=supplier.id,order_number="PO-"+uuid.uuid4().hex[:14].upper(),status="draft",
        currency=quote.currency,notes="Awarded from "+rfq.rfq_number,created_by=user.id)
    db.add(order);db.flush()
    quote_map={x.rfq_line_id:x for x in quote_lines}
    for line in rfq_lines:
        qline=quote_map[line.id]
        db.add(ProcurementPurchaseOrderLine(organization_id=membership.organization_id,purchase_order_id=order.id,
            product_id=line.product_id,quantity_ordered=line.quantity,quantity_received=Decimal("0"),unit_cost=qline.unit_price))
    rfq.status="awarded"
    audit(db,user.id,membership.organization_id,"procurement.rfq.awarded","procurement_rfq",rfq.id,order.order_number)
    db.commit()
    return {"id":order.id,"order_number":order.order_number,"status":order.status,"supplier_id":supplier.id}


@router.post("/procurement/supplier-invoices",status_code=201)
def create_supplier_invoice(payload:SupplierInvoiceIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    supplier=db.query(ProcurementSupplier).filter_by(id=payload.supplier_id,organization_id=membership.organization_id,is_active=True).first()
    order=db.query(ProcurementPurchaseOrder).filter_by(id=payload.purchase_order_id,organization_id=membership.organization_id,supplier_id=payload.supplier_id).first()
    if not supplier or not order:raise HTTPException(404,"Supplier or purchase order not found")
    _procurement_branch_check(db,membership,order.branch_id)
    if order.status not in {"received","partially_received"}:raise HTTPException(409,"Only received purchase orders can be invoiced")
    if payload.currency!=order.currency:raise HTTPException(409,"Invoice currency must match the purchase order currency")
    subtotal=Decimal("0")
    for line in payload.lines:
        po=db.query(ProcurementPurchaseOrderLine).filter_by(id=line.purchase_order_line_id,purchase_order_id=order.id,organization_id=membership.organization_id).first()
        if not po:raise HTTPException(404,"Invoice line does not belong to this purchase order")
        if po.unit_cost!=line.unit_cost:raise HTTPException(409,"Invoice unit cost does not match purchase order")
        inspected=db.query(func.coalesce(func.sum(ProcurementGoodsReceiptLine.quantity_accepted),0)).join(
            ProcurementGoodsReceipt,ProcurementGoodsReceipt.id==ProcurementGoodsReceiptLine.goods_receipt_id).filter(
            ProcurementGoodsReceipt.purchase_order_id==order.id,ProcurementGoodsReceipt.status=="inspected",
            ProcurementGoodsReceiptLine.purchase_order_line_id==po.id).scalar() or Decimal("0")
        prior=db.query(func.coalesce(func.sum(ProcurementSupplierInvoiceLine.quantity),0)).join(
            ProcurementSupplierInvoice,ProcurementSupplierInvoice.id==ProcurementSupplierInvoiceLine.invoice_id).filter(
            ProcurementSupplierInvoice.purchase_order_id==order.id,ProcurementSupplierInvoiceLine.purchase_order_line_id==po.id,
            ProcurementSupplierInvoice.status.in_(["pending_match","matched"])).scalar() or Decimal("0")
        returned=db.query(func.coalesce(func.sum(ProcurementSupplierReturnLine.quantity),0)).join(
            ProcurementSupplierReturn,ProcurementSupplierReturn.id==ProcurementSupplierReturnLine.return_id).join(
            ProcurementGoodsReceiptLine,ProcurementGoodsReceiptLine.id==ProcurementSupplierReturnLine.receipt_line_id).filter(
            ProcurementSupplierReturn.organization_id==membership.organization_id,
            ProcurementGoodsReceiptLine.purchase_order_line_id==po.id).scalar() or Decimal("0")
        if line.quantity>inspected-prior-returned:raise HTTPException(409,"Invoice quantity exceeds accepted, non-returned, uninvoiced GRN quantity")
        subtotal+=line.quantity*line.unit_cost
    invoice=ProcurementSupplierInvoice(organization_id=membership.organization_id,supplier_id=supplier.id,
        purchase_order_id=order.id,invoice_number=payload.invoice_number,invoice_date=datetime.combine(payload.invoice_date,time.min),
        currency=payload.currency,status="matched",subtotal=subtotal,tax_total=payload.tax_total,created_by=user.id,
        matched_by=user.id,matched_at=datetime.now(timezone.utc))
    db.add(invoice);db.flush()
    for x in payload.lines:db.add(ProcurementSupplierInvoiceLine(organization_id=membership.organization_id,invoice_id=invoice.id,
        purchase_order_line_id=x.purchase_order_line_id,quantity=x.quantity,unit_cost=x.unit_cost))
    audit(db,user.id,membership.organization_id,"procurement.invoice.three_way_matched","supplier_invoice",invoice.id,payload.invoice_number)
    db.commit()
    return {"id":invoice.id,"invoice_number":invoice.invoice_number,"status":invoice.status,"subtotal":str(subtotal),"tax_total":str(invoice.tax_total),"total":str(subtotal+invoice.tax_total)}


@router.post("/procurement/goods-receipts/{receipt_id}/returns",status_code=201)
def return_goods_to_supplier(receipt_id:int,payload:SupplierReturnIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    receipt=db.query(ProcurementGoodsReceipt).filter_by(id=receipt_id,organization_id=membership.organization_id).with_for_update().first()
    if not receipt:raise HTTPException(404,"Goods receipt not found")
    if receipt.status!="inspected":raise HTTPException(409,"Only inspected goods can be returned")
    _procurement_branch_check(db,membership,receipt.branch_id)
    rows={x.id:x for x in db.query(ProcurementGoodsReceiptLine).filter_by(goods_receipt_id=receipt.id,organization_id=membership.organization_id).with_for_update().all()}
    if not set(x.receipt_line_id for x in payload.lines)<=set(rows):raise HTTPException(422,"Return lines must belong to this receipt")
    returned=[]
    for item in payload.lines:
        row=rows[item.receipt_line_id]
        already=db.query(func.coalesce(func.sum(ProcurementSupplierReturnLine.quantity),0)).join(
            ProcurementSupplierReturn,ProcurementSupplierReturn.id==ProcurementSupplierReturnLine.return_id).filter(
            ProcurementSupplierReturnLine.receipt_line_id==row.id,ProcurementSupplierReturn.organization_id==membership.organization_id).scalar() or Decimal("0")
        if item.quantity>row.quantity_accepted-already:raise HTTPException(409,"Return quantity exceeds accepted quantity not previously returned")
        stock=db.query(func.coalesce(func.sum(InventoryStockMovement.quantity_delta),0)).filter(
            InventoryStockMovement.organization_id==membership.organization_id,
            InventoryStockMovement.product_id==row.product_id,
            InventoryStockMovement.branch_id==receipt.branch_id).scalar() or Decimal("0")
        resulting_balance(Decimal(stock),-item.quantity)
        returned.append((row,item.quantity))
    po=db.query(ProcurementPurchaseOrder).filter_by(id=receipt.purchase_order_id,organization_id=membership.organization_id).first()
    ret=ProcurementSupplierReturn(organization_id=membership.organization_id,goods_receipt_id=receipt.id,
        supplier_id=po.supplier_id,return_number="RET-"+uuid.uuid4().hex[:14].upper(),status="posted",
        reason=payload.reason.strip(),credit_note_reference=payload.credit_note_reference.strip(),created_by=user.id)
    db.add(ret);db.flush()
    for row,qty in returned:
        db.add(ProcurementSupplierReturnLine(organization_id=membership.organization_id,return_id=ret.id,receipt_line_id=row.id,quantity=qty))
        db.add(InventoryStockMovement(organization_id=membership.organization_id,product_id=row.product_id,
            branch_id=receipt.branch_id,quantity_delta=-qty,movement_type="issue",reference=ret.return_number,
            idempotency_key="supplier-return-"+str(ret.id)+"-"+str(row.id),created_by=user.id))
    audit(db,user.id,membership.organization_id,"procurement.supplier_return.posted","supplier_return",ret.id,payload.reason)
    db.commit()
    return {"id":ret.id,"return_number":ret.return_number,"status":ret.status,"credit_note_reference":ret.credit_note_reference}


@router.get("/procurement/supplier-performance")
def procurement_supplier_performance(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    suppliers=db.query(ProcurementSupplier).filter_by(organization_id=membership.organization_id).all()
    output=[]
    for s in suppliers:
        orders=db.query(ProcurementPurchaseOrder).filter_by(organization_id=membership.organization_id,supplier_id=s.id).all()
        receipts=db.query(ProcurementGoodsReceipt).filter_by(organization_id=membership.organization_id).join(
            ProcurementPurchaseOrder,ProcurementPurchaseOrder.id==ProcurementGoodsReceipt.purchase_order_id).filter(
            ProcurementPurchaseOrder.supplier_id==s.id).all()
        accepted=sum((x.quantity_accepted for x in db.query(ProcurementGoodsReceiptLine).join(
            ProcurementGoodsReceipt,ProcurementGoodsReceipt.id==ProcurementGoodsReceiptLine.goods_receipt_id).filter(
            ProcurementGoodsReceipt.organization_id==membership.organization_id,ProcurementGoodsReceipt.status=="inspected",
            ProcurementGoodsReceipt.purchase_order_id.in_([o.id for o in orders] or [-1])).all()),Decimal("0"))
        delivered=sum((x.quantity_received for x in db.query(ProcurementGoodsReceiptLine).join(
            ProcurementGoodsReceipt,ProcurementGoodsReceipt.id==ProcurementGoodsReceiptLine.goods_receipt_id).filter(
            ProcurementGoodsReceipt.organization_id==membership.organization_id,ProcurementGoodsReceipt.purchase_order_id.in_([o.id for o in orders] or [-1])).all()),Decimal("0"))
        output.append({"supplier_id":s.id,"supplier":s.name,"purchase_orders":len(orders),"goods_receipts":len(receipts),
            "delivered_quantity":str(delivered),"accepted_quantity":str(accepted),
            "acceptance_rate_percent":str((accepted/delivered*100).quantize(Decimal("0.01")) if delivered else Decimal("0"))})
    return output


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
                       "tax_rate": str(product.tax_rate),
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


def _pos_shift_cash_totals(db,shift):
    sales=db.query(func.coalesce(func.sum(POSPayment.amount),0)).join(POSSale,POSSale.id==POSPayment.sale_id).filter(
        POSSale.organization_id==shift.organization_id,POSSale.shift_id==shift.id,POSPayment.method=="cash",POSPayment.status=="recorded").scalar()
    refunds=db.query(func.coalesce(func.sum(POSRefund.amount),0)).join(POSReturn,POSReturn.id==POSRefund.return_id).join(
        POSSale,POSSale.id==POSReturn.sale_id).filter(POSRefund.organization_id==shift.organization_id,
        POSReturn.organization_id==shift.organization_id,POSSale.organization_id==shift.organization_id,
        POSSale.shift_id==shift.id,POSRefund.method=="cash",POSRefund.status=="recorded").scalar()
    moves=db.query(POSCashMovement).filter_by(organization_id=shift.organization_id,shift_id=shift.id,status="recorded").all()
    ci=sum((Decimal(str(x.amount)) for x in moves if x.movement_type=="cash_in"),Decimal("0"))
    co=sum((Decimal(str(x.amount)) for x in moves if x.movement_type in ("cash_out","safe_drop")),Decimal("0"))
    sales,refunds=Decimal(str(sales or 0)),Decimal(str(refunds or 0))
    return {"sales":sales,"refunds":refunds,"cash_in":ci,"cash_out":co,"expected":Decimal(str(shift.opening_cash))+sales-refunds+ci-co,"moves":moves}


@router.post("/pos/shifts/{shift_id}/cash-movements",status_code=201)
def create_pos_cash_movement(shift_id:int,payload:POSCashMovementIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    shift=db.query(POSShift).filter_by(id=shift_id,organization_id=membership.organization_id,cashier_user_id=user.id,status="open").with_for_update().first()
    if not shift or not can_access_branch(membership,shift.branch_id): raise HTTPException(404,"Open cashier shift not found")
    old=db.query(POSCashMovement).filter_by(organization_id=membership.organization_id,idempotency_key=payload.idempotency_key).first()
    if old:
        if (old.shift_id!=shift.id or old.movement_type!=payload.movement_type
            or Decimal(str(old.amount))!=payload.amount or old.reason!=payload.reason.strip()
            or old.reference!=payload.reference.strip()):
            raise HTTPException(409,"Idempotency key conflict")
        return {"id":old.id,"status":"already_recorded","amount":str(old.amount)}
    if payload.movement_type in ("cash_out","safe_drop"):
        require_permission(membership,"manage")
        totals=_pos_shift_cash_totals(db,shift)
        if payload.amount > totals["expected"]:
            raise HTTPException(422,"Cash out or safe drop exceeds the available till cash")
    row=POSCashMovement(organization_id=membership.organization_id,branch_id=shift.branch_id,shift_id=shift.id,
        movement_type=payload.movement_type,amount=payload.amount,reason=payload.reason.strip(),reference=payload.reference.strip(),
        idempotency_key=payload.idempotency_key,created_by=user.id,authorized_by=user.id if payload.movement_type!="cash_in" else None)
    db.add(row)
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(409,"Cash movement conflicts with another request")
    db.refresh(row); audit(db,user.id,membership.organization_id,"pos.cash_movement.recorded","pos_cash_movement",row.id,f"{row.movement_type}:{row.amount}:{row.reason}")
    return {"id":row.id,"status":row.status,"movement_type":row.movement_type,"amount":str(row.amount)}


@router.get("/pos/shifts/{shift_id}/reconciliation")
def pos_shift_reconciliation(shift_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    shift=db.query(POSShift).filter_by(id=shift_id,organization_id=membership.organization_id).first()
    if not shift or not can_access_branch(membership,shift.branch_id): raise HTTPException(404,"POS shift not found")
    if shift.cashier_user_id!=user.id: require_permission(membership,"manage")
    x=_pos_shift_cash_totals(db,shift)
    return {"id":shift.id,"status":shift.status,"reconciliation_status":shift.reconciliation_status,"opening_cash":str(shift.opening_cash),
        "cash_sales":str(x["sales"]),"cash_refunds":str(x["refunds"]),"cash_in":str(x["cash_in"]),"cash_out_and_safe_drops":str(x["cash_out"]),
        "expected_cash":str(shift.expected_cash if shift.expected_cash is not None else x["expected"]),
        "counted_cash":str(shift.counted_cash) if shift.counted_cash is not None else None,
        "variance":str(shift.cash_variance) if shift.cash_variance is not None else None,
        "denominations":shift.counted_denominations or {},"close_note":shift.close_note,"review_note":shift.review_note,
        "reviewed_by":shift.reviewed_by,"movements":[{"id":v.id,"type":v.movement_type,"amount":str(v.amount),"reason":v.reason,
        "reference":v.reference,"created_by":v.created_by} for v in x["moves"]]}


@router.post("/pos/shifts/{shift_id}/close")
def close_pos_shift(shift_id:int,payload:POSShiftCloseIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"update")
    shift=db.query(POSShift).filter_by(id=shift_id,organization_id=membership.organization_id,cashier_user_id=user.id,status="open").with_for_update().first()
    if not shift or not can_access_branch(membership,shift.branch_id): raise HTTPException(404,"Open shift not found")
    x=_pos_shift_cash_totals(db,shift); expected=x["expected"]; variance=payload.closing_cash-expected
    shift.closing_cash=payload.closing_cash; shift.counted_cash=payload.closing_cash; shift.expected_cash=expected
    shift.cash_variance=variance; shift.counted_denominations=payload.cash_count; shift.close_note=payload.note.strip()
    shift.status="closed"; shift.closed_at=datetime.now(timezone.utc)
    shift.reconciliation_status="reconciled" if variance==0 else "pending_review"
    if variance==0:
        shift.reviewed_by=user.id; shift.reviewed_at=datetime.now(timezone.utc); shift.review_note="Automatically reconciled: no variance"
    db.commit()
    audit(db,user.id,membership.organization_id,"pos.shift.closed","pos_shift",shift.id,f"expected:{expected};counted:{payload.closing_cash};variance:{variance}")
    return {"id":shift.id,"status":shift.status,"reconciliation_status":shift.reconciliation_status,"expected_cash":str(expected),
        "closing_cash":str(payload.closing_cash),"variance":str(variance),"requires_review":variance!=0}


@router.post("/pos/shifts/{shift_id}/review")
def review_pos_shift(shift_id:int,payload:POSShiftReviewIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    shift=db.query(POSShift).filter_by(id=shift_id,organization_id=membership.organization_id,status="closed").with_for_update().first()
    if not shift or not can_access_branch(membership,shift.branch_id): raise HTTPException(404,"Closed POS shift not found")
    if shift.reconciliation_status!="pending_review": raise HTTPException(409,"Only pending variances can be reviewed")
    shift.reconciliation_status="approved" if payload.decision=="approve" else "rejected"
    shift.reviewed_by=user.id; shift.reviewed_at=datetime.now(timezone.utc); shift.review_note=payload.note.strip()
    db.commit(); audit(db,user.id,membership.organization_id,"pos.shift.reconciliation_reviewed","pos_shift",shift.id,payload.decision+":"+payload.note)
    return {"id":shift.id,"reconciliation_status":shift.reconciliation_status,"reviewed_by":user.id}


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
        existing_payments = db.query(POSPayment).filter_by(
            organization_id=membership.organization_id, sale_id=existing.id
        ).order_by(POSPayment.id).all()
        return {"id": existing.id, "client_transaction_id": existing.client_transaction_id,
                "status": "already_synced", "total_amount": str(existing.total_amount),
                "payments": [{"id": p.id, "method": p.method, "amount": str(p.amount), "status": p.status}
                             for p in existing_payments]}
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
    if any(Decimal(str(line.discount_percent)) > 0 for line in payload.lines):
        require_permission(membership, "manage")
    subtotal_total = Decimal("0.00")
    discount_total = Decimal("0.00")
    tax_total = Decimal("0.00")
    total = Decimal("0.00")
    prepared = []
    aggregate_qty = {}
    for line in payload.lines:
        product = product_map[line.product_id]
        unit_price = money(Decimal(str(product.sale_price)))
        if Decimal(str(product.tax_rate)) < 0 or Decimal(str(product.tax_rate)) > 100:
            raise HTTPException(409, f"Product {product.sku} has an invalid configured tax rate")
        subtotal, discount, tax, line_total = calculate_pos_line(
            unit_price, line.quantity, Decimal(str(line.discount_percent)),
            Decimal(str(product.tax_rate)))
        if line_total <= 0:
            raise HTTPException(409, f"Product {product.sku} has no configured sale price after discount")
        subtotal_total += subtotal
        discount_total += discount
        tax_total += tax
        total += line_total
        aggregate_qty[line.product_id] = aggregate_qty.get(line.product_id, Decimal("0")) + line.quantity
        prepared.append((line, unit_price, subtotal, discount, Decimal(str(product.tax_rate)), tax, line_total))
    subtotal_total, discount_total, tax_total, total = map(
        money, (subtotal_total, discount_total, tax_total, total))
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
        total_amount=total, subtotal_amount=subtotal_total,
        discount_amount=discount_total, tax_amount=tax_total,
        currency=payload.currency, status="posted",
        offline_created_at=payload.offline_created_at
    )
    db.add(sale)
    db.flush()
    for index, (line, unit_price, subtotal, discount, tax_rate, tax, line_total) in enumerate(prepared):
        db.add(POSSaleLine(organization_id=membership.organization_id, sale_id=sale.id,
                           product_id=line.product_id, quantity=line.quantity,
                           unit_price=unit_price, discount_percent=line.discount_percent,
                           discount_amount=discount, tax_rate=tax_rate,
                           tax_amount=tax, line_total=line_total))
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
            status="unsettled" if payment.method in {"credit", "mpesa"} else "recorded"
        ))
    # Auto-post the source and journal in the same transaction. Missing mappings
    # create a durable pending bridge item without blocking checkout.
    from app.api.accounting_pos import post_pos_source
    accounting_link = post_pos_source(
        db, membership.organization_id, sale.branch_id, "sale", sale.id, user.id
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(POSSale).filter_by(
            organization_id=membership.organization_id,
            client_transaction_id=payload.client_transaction_id
        ).first()
        if existing and existing.request_hash == request_hash:
            existing_payments = db.query(POSPayment).filter_by(
                organization_id=membership.organization_id, sale_id=existing.id
            ).order_by(POSPayment.id).all()
            return {"id": existing.id, "client_transaction_id": existing.client_transaction_id,
                    "status": "already_synced", "total_amount": str(existing.total_amount),
                    "payments": [{"id": p.id, "method": p.method, "amount": str(p.amount), "status": p.status}
                                 for p in existing_payments]}
        raise HTTPException(409, "POS transaction conflicts with an existing synchronization")
    db.refresh(sale)
    audit(db, user.id, membership.organization_id, "pos.sale.synced",
          "pos_sale", sale.id, payload.client_transaction_id)
    sale_payments = db.query(POSPayment).filter_by(
        organization_id=membership.organization_id, sale_id=sale.id
    ).order_by(POSPayment.id).all()
    return {"id": sale.id, "client_transaction_id": sale.client_transaction_id,
            "status": "synced", "total_amount": str(sale.total_amount), "currency": sale.currency,
            "payments": [{"id": p.id, "method": p.method, "amount": str(p.amount), "status": p.status}
                         for p in sale_payments],
            "accounting_status": accounting_link.status, "accounting_journal_id": accounting_link.journal_id}



@router.get("/pos/sales/{sale_id}")
def get_pos_sale_receipt(sale_id: int, membership=Depends(active_membership),
                         user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    sale = db.query(POSSale).filter_by(
        id=sale_id, organization_id=membership.organization_id
    ).first()
    if not sale or not can_access_branch(membership, sale.branch_id):
        raise HTTPException(404, "Sale not found")
    lines = db.query(POSSaleLine, InventoryProduct.name, InventoryProduct.sku).join(
        InventoryProduct, InventoryProduct.id == POSSaleLine.product_id
    ).filter(POSSaleLine.organization_id == membership.organization_id,
             POSSaleLine.sale_id == sale.id).order_by(POSSaleLine.id).all()
    returned = db.query(
        POSReturnLine.sale_line_id,
        func.coalesce(func.sum(POSReturnLine.quantity), 0),
        func.coalesce(func.sum(POSReturnLine.line_total), 0),
    ).join(POSReturn, POSReturn.id == POSReturnLine.return_id).filter(
        POSReturn.organization_id == membership.organization_id,
        POSReturn.sale_id == sale.id
    ).group_by(POSReturnLine.sale_line_id).all()
    returned_map = {
        line_id: (Decimal(str(quantity)), Decimal(str(value)))
        for line_id, quantity, value in returned
    }
    payments = db.query(POSPayment).filter_by(
        organization_id=membership.organization_id, sale_id=sale.id
    ).order_by(POSPayment.id).all()
    return {
        "id": sale.id, "branch_id": sale.branch_id, "shift_id": sale.shift_id,
        "currency": sale.currency, "status": sale.status,
        "total_amount": str(sale.total_amount),
        "subtotal_amount": str(sale.subtotal_amount),
        "discount_amount": str(sale.discount_amount),
        "tax_amount": str(sale.tax_amount),
        "created_at": sale.created_at.isoformat(),
        "lines": [{
            "id": line.id, "product_id": line.product_id, "sku": sku, "name": name,
            "quantity": str(line.quantity),
            "returned_quantity": str(returned_map.get(line.id, (Decimal("0"), Decimal("0")))[0]),
            "returnable_quantity": str(Decimal(str(line.quantity)) - returned_map.get(line.id, (Decimal("0"), Decimal("0")))[0]),
            "returnable_value": str(Decimal(str(line.line_total)) - returned_map.get(line.id, (Decimal("0"), Decimal("0")))[1]),
            "unit_price": str(line.unit_price),
            "discount_percent": str(line.discount_percent),
            "discount_amount": str(line.discount_amount),
            "tax_rate": str(line.tax_rate), "tax_amount": str(line.tax_amount),
            "line_total": str(line.line_total),
        } for line, name, sku in lines],
        "payments": [{"id": p.id, "method": p.method, "amount": str(p.amount), "status": p.status,
                      "provider_reference": p.provider_reference} for p in payments],
    }


@router.post("/pos/sales/{sale_id}/returns", status_code=201)
def create_pos_return(sale_id: int, payload: POSReturnIn,
                      membership=Depends(active_membership), user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    # Refunds and stock reintegration require a supervisor/manager permission.
    require_permission(membership, "manage")
    request_hash = canonical_return_hash(payload)
    existing = db.query(POSReturn).filter_by(
        organization_id=membership.organization_id, client_return_id=payload.client_return_id
    ).first()
    if existing:
        if existing.request_hash != request_hash or existing.sale_id != sale_id:
            raise HTTPException(409, "Return ID was already used for different return data")
        return {"id": existing.id, "sale_id": existing.sale_id, "status": "already_recorded",
                "refund_total": str(existing.refund_total)}
    sale = db.query(POSSale).filter_by(
        id=sale_id, organization_id=membership.organization_id, status="posted"
    ).with_for_update().first()
    if not sale or not can_access_branch(membership, sale.branch_id):
        raise HTTPException(404, "Sale not found")
    line_ids = [item.sale_line_id for item in payload.lines]
    sale_lines = db.query(POSSaleLine).filter(
        POSSaleLine.organization_id == membership.organization_id,
        POSSaleLine.sale_id == sale.id, POSSaleLine.id.in_(line_ids)
    ).with_for_update().all()
    line_map = {item.id: item for item in sale_lines}
    if set(line_map) != set(line_ids):
        raise HTTPException(404, "One or more original sale lines were not found")
    already_returned = db.query(
        POSReturnLine.sale_line_id,
        func.coalesce(func.sum(POSReturnLine.quantity), 0),
        func.coalesce(func.sum(POSReturnLine.line_total), 0),
        func.coalesce(func.sum(POSReturnLine.discount_amount), 0),
        func.coalesce(func.sum(POSReturnLine.tax_amount), 0),
    ).join(POSReturn, POSReturn.id == POSReturnLine.return_id).filter(
        POSReturn.organization_id == membership.organization_id,
        POSReturn.sale_id == sale.id,
        POSReturnLine.sale_line_id.in_(line_ids)
    ).group_by(POSReturnLine.sale_line_id).all()
    returned_map = {
        line_id: tuple(Decimal(str(value)) for value in (quantity, amount, discount, tax))
        for line_id, quantity, amount, discount, tax in already_returned
    }
    total = Decimal("0.00")
    prepared = []
    for item in payload.lines:
        original = line_map[item.sale_line_id]
        returned_qty, returned_value, returned_discount, returned_tax = returned_map.get(
            original.id, (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")))
        remaining = Decimal(str(original.quantity)) - returned_qty
        if item.quantity > remaining:
            raise HTTPException(409, f"Return quantity exceeds remaining sold quantity for line {original.id}")
        if item.quantity == remaining:
            amount = money(Decimal(str(original.line_total)) - returned_value)
            discount_amount = money(Decimal(str(original.discount_amount)) - returned_discount)
            tax_amount = money(Decimal(str(original.tax_amount)) - returned_tax)
        else:
            ratio = Decimal(str(item.quantity)) / Decimal(str(original.quantity))
            amount = money(Decimal(str(original.line_total)) * ratio)
            discount_amount = money(Decimal(str(original.discount_amount)) * ratio)
            tax_amount = money(Decimal(str(original.tax_amount)) * ratio)
        total += amount
        prepared.append((original, item.quantity, amount, discount_amount, tax_amount))
    total = money(total)
    validate_return_refund_total(total, payload.refunds)
    original_tenders = db.query(POSPayment.method,
        func.coalesce(func.sum(POSPayment.amount), 0)).filter(
        POSPayment.organization_id == membership.organization_id,
        POSPayment.sale_id == sale.id, POSPayment.status == "recorded"
    ).group_by(POSPayment.method).all()
    tender_totals = {method: Decimal(str(amount)) for method, amount in original_tenders}
    prior_refunds = db.query(POSRefund.method,
        func.coalesce(func.sum(POSRefund.amount), 0)).join(
        POSReturn, POSReturn.id == POSRefund.return_id
    ).filter(POSReturn.organization_id == membership.organization_id,
             POSReturn.sale_id == sale.id).group_by(POSRefund.method).all()
    prior_map = {method: Decimal(str(amount)) for method, amount in prior_refunds}
    requested_map = {}
    for item in payload.refunds:
        requested_map[item.method] = requested_map.get(item.method, Decimal("0")) + money(item.amount)
    for method, amount in requested_map.items():
        if amount + prior_map.get(method, Decimal("0")) > tender_totals.get(method, Decimal("0")):
            raise HTTPException(422, f"Refund by {method} exceeds recorded original tender available")
    result = POSReturn(
        organization_id=membership.organization_id, sale_id=sale.id, branch_id=sale.branch_id,
        client_return_id=payload.client_return_id, request_hash=request_hash,
        reason=payload.reason.strip(), refund_total=total, created_by=user.id,
    )
    db.add(result)
    db.flush()
    return_key = hashlib.sha256(payload.client_return_id.encode()).hexdigest()[:32]
    for index, (original, quantity, amount, discount_amount, tax_amount) in enumerate(prepared):
        db.add(POSReturnLine(organization_id=membership.organization_id, return_id=result.id,
            sale_line_id=original.id, product_id=original.product_id, quantity=quantity,
            unit_price=original.unit_price, discount_amount=discount_amount,
            tax_amount=tax_amount, line_total=amount))
        db.add(InventoryStockMovement(organization_id=membership.organization_id,
            product_id=original.product_id, branch_id=sale.branch_id, quantity_delta=quantity,
            movement_type="receipt", reference=payload.client_return_id,
            idempotency_key=f"pos-return:{return_key}:{index}", created_by=user.id))
    for item in payload.refunds:
        db.add(POSRefund(organization_id=membership.organization_id, return_id=result.id,
            method=item.method, amount=money(item.amount), provider_reference=item.provider_reference,
            status="pending" if item.method == "mpesa" else "recorded"))
    from app.api.accounting_pos import post_pos_source
    accounting_link = post_pos_source(
        db, membership.organization_id, result.branch_id, "return", result.id, user.id
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(POSReturn).filter_by(
            organization_id=membership.organization_id, client_return_id=payload.client_return_id
        ).first()
        if existing and existing.request_hash == request_hash and existing.sale_id == sale_id:
            existing_refunds = db.query(POSRefund).filter_by(
                organization_id=membership.organization_id, return_id=existing.id
            ).order_by(POSRefund.id).all()
            return {"id": existing.id, "sale_id": existing.sale_id, "status": "already_recorded",
                    "refund_total": str(existing.refund_total),
                    "refunds": [{"id": item.id, "method": item.method, "amount": str(item.amount),
                                 "status": item.status} for item in existing_refunds]}
        raise HTTPException(409, "Return conflicts with another return or stock movement")
    db.refresh(result)
    audit(db, user.id, membership.organization_id, "pos.sale.returned",
          "pos_return", result.id, f"sale:{sale.id};refund:{total};reason:{payload.reason.strip()}")
    return {"id": result.id, "sale_id": sale.id, "status": "recorded",
            "refund_total": str(result.refund_total), "currency": sale.currency,
            "stock_reintegrated": True, "refunds_executed": False,
            "accounting_status": accounting_link.status,
            "accounting_journal_id": accounting_link.journal_id,
            "refunds": [{"id": item.id, "method": item.method, "amount": str(item.amount), "status": item.status}
                        for item in db.query(POSRefund).filter_by(
                            organization_id=membership.organization_id, return_id=result.id
                        ).order_by(POSRefund.id).all()]}


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


def _accounting_assert_period_open(db, organization_id, entry_date):
    closed=db.query(AccountingFiscalPeriod).filter(
        AccountingFiscalPeriod.organization_id==organization_id,
        AccountingFiscalPeriod.status=="closed",
        AccountingFiscalPeriod.start_date<=datetime.combine(entry_date,time.max,tzinfo=timezone.utc),
        AccountingFiscalPeriod.end_date>=datetime.combine(entry_date,time.min,tzinfo=timezone.utc)
    ).first()
    if closed:
        raise HTTPException(409,"The accounting date falls inside a closed fiscal period")


def _accounting_make_journal(db, membership, user, entry_date, reference, memo, lines, branch_id=None):
    _accounting_assert_period_open(db,membership.organization_id,entry_date)
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


@router.post("/accounting/invoices/{invoice_id}/submit-for-approval")
def submit_accounting_invoice_for_approval(invoice_id: int, membership=Depends(active_membership),
    user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "create")
    invoice=db.query(AccountingInvoice).filter_by(
        id=invoice_id, organization_id=membership.organization_id).with_for_update().first()
    if not invoice: raise HTTPException(404, "Invoice not found")
    if invoice.branch_id and not can_access_branch(membership, invoice.branch_id):
        raise HTTPException(404, "Invoice not found")
    if invoice.status != "draft": raise HTTPException(409, "Only draft invoices can be submitted")
    existing=db.query(AccountingInvoiceApproval).filter_by(
        organization_id=membership.organization_id, invoice_id=invoice.id).with_for_update().first()
    if existing and existing.status == "pending":
        raise HTTPException(409, "Invoice approval is already pending")
    if existing and existing.status == "approved":
        raise HTTPException(409, "Invoice has already been approved")
    if existing:
        existing.submitted_by=user.id; existing.submitted_at=datetime.now(timezone.utc)
        existing.approver_user_id=None; existing.status="pending"; existing.decision_note=""; existing.decided_at=None
    else:
        existing=AccountingInvoiceApproval(organization_id=membership.organization_id,
            invoice_id=invoice.id,submitted_by=user.id,status="pending")
        db.add(existing)
    db.commit()
    audit(db,user.id,membership.organization_id,"accounting.invoice.submitted_for_approval",
        "accounting_invoice",invoice.id)
    return {"invoice_id":invoice.id,"approval_status":"pending"}


@router.get("/accounting/invoices/{invoice_id}/approval")
def get_accounting_invoice_approval(invoice_id:int,membership=Depends(active_membership),
    db:Session=Depends(get_db)):
    require_permission(membership,"read")
    invoice=db.query(AccountingInvoice).filter_by(id=invoice_id,
        organization_id=membership.organization_id).first()
    if not invoice or (invoice.branch_id and not can_access_branch(membership,invoice.branch_id)):
        raise HTTPException(404,"Invoice not found")
    row=db.query(AccountingInvoiceApproval).filter_by(
        organization_id=membership.organization_id,invoice_id=invoice.id).first()
    if not row: return {"invoice_id":invoice.id,"approval_status":"not_required"}
    return {"invoice_id":invoice.id,"approval_status":row.status,"submitted_by":row.submitted_by,
        "submitted_at":row.submitted_at.isoformat(),"approver_user_id":row.approver_user_id,
        "decision_note":row.decision_note,"decided_at":row.decided_at.isoformat() if row.decided_at else None}


@router.post("/accounting/invoices/{invoice_id}/approval-decision")
def decide_accounting_invoice_approval(invoice_id:int,payload:AccountingInvoiceApprovalDecisionIn,
    membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    invoice=db.query(AccountingInvoice).filter_by(id=invoice_id,
        organization_id=membership.organization_id).with_for_update().first()
    if not invoice or (invoice.branch_id and not can_access_branch(membership,invoice.branch_id)):
        raise HTTPException(404,"Invoice not found")
    row=db.query(AccountingInvoiceApproval).filter_by(
        organization_id=membership.organization_id,invoice_id=invoice.id).with_for_update().first()
    if not row or row.status!="pending": raise HTTPException(409,"Invoice has no pending approval")
    if row.submitted_by==user.id: raise HTTPException(409,"Invoice submitter cannot approve their own invoice")
    if row.approver_user_id==user.id: raise HTTPException(409,"Approver has already acted on this invoice")
    row.status=payload.decision
    row.approver_user_id=user.id
    row.decision_note=payload.note.strip()
    row.decided_at=datetime.now(timezone.utc)
    db.commit()
    audit(db,user.id,membership.organization_id,"accounting.invoice.approval_"+payload.decision,
        "accounting_invoice",invoice.id,row.decision_note)
    return {"invoice_id":invoice.id,"approval_status":row.status,"approver_user_id":user.id}


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
    approval=db.query(AccountingInvoiceApproval).filter_by(
        organization_id=membership.organization_id,invoice_id=invoice.id).first()
    if approval and approval.status!="approved":
        raise HTTPException(409,"Invoice must be approved before posting")

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


@router.post("/accounting/invoices/{invoice_id}/credit-notes",status_code=201)
def create_accounting_credit_note(invoice_id:int,payload:AccountingCreditNoteIn,
    membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    invoice=db.query(AccountingInvoice).filter_by(id=invoice_id,
        organization_id=membership.organization_id).with_for_update().first()
    if not invoice or (invoice.branch_id and not can_access_branch(membership,invoice.branch_id)):
        raise HTTPException(404,"Invoice not found")
    if invoice.status not in ("posted","partially_paid","paid"):
        raise HTTPException(409,"Only posted invoices can be credited")
    duplicate=db.query(AccountingCreditNote).filter_by(
        organization_id=membership.organization_id,idempotency_key=payload.idempotency_key).first()
    if duplicate:
        if duplicate.invoice_id==invoice.id and duplicate.credit_note_number==payload.credit_note_number:
            return {"id":duplicate.id,"credit_note_number":duplicate.credit_note_number,"status":duplicate.status}
        raise HTTPException(409,"Credit note idempotency key has already been used")
    existing_number=db.query(AccountingCreditNote).filter_by(
        organization_id=membership.organization_id,credit_note_number=payload.credit_note_number.strip().upper()).first()
    if existing_number: raise HTTPException(409,"Credit note number already exists")
    _accounting_assert_period_open(db,membership.organization_id,payload.issue_date)
    invoice_lines={x.id:x for x in db.query(AccountingInvoiceLine).filter_by(
        organization_id=membership.organization_id,invoice_id=invoice.id).with_for_update().all()}
    if {x.invoice_line_id for x in payload.lines} - set(invoice_lines):
        raise HTTPException(422,"Credit note lines must belong to this invoice")
    subtotal=Decimal("0.00");tax_total=Decimal("0.00");allocations=[]
    for item in payload.lines:
        source=invoice_lines[item.invoice_line_id]
        credited=db.query(func.coalesce(func.sum(AccountingCreditNoteLine.quantity),0)).join(
            AccountingCreditNote,AccountingCreditNote.id==AccountingCreditNoteLine.credit_note_id).filter(
            AccountingCreditNote.organization_id==membership.organization_id,
            AccountingCreditNote.invoice_id==invoice.id,
            AccountingCreditNote.status=="posted",
            AccountingCreditNoteLine.invoice_line_id==source.id).scalar() or Decimal("0")
        if item.quantity>Decimal(source.quantity)-Decimal(credited):
            raise HTTPException(409,"Credit quantity exceeds the uncredited invoice quantity")
        line_sub=(item.quantity*Decimal(source.unit_price)).quantize(Decimal("0.01"))
        line_tax=(line_sub*Decimal(source.tax_rate)/Decimal("100")).quantize(Decimal("0.01"))
        subtotal+=line_sub;tax_total+=line_tax
        allocations.append((source,item.quantity,line_sub,line_tax,line_sub+line_tax))
    total=subtotal+tax_total
    remaining_invoice_value = Decimal(invoice.total)
    if total > remaining_invoice_value:
        raise HTTPException(409,"Credit exceeds the remaining uncredited invoice value")
    note=AccountingCreditNote(organization_id=membership.organization_id,invoice_id=invoice.id,
        branch_id=invoice.branch_id,credit_note_number=payload.credit_note_number.strip().upper(),
        issue_date=datetime.combine(payload.issue_date,time.min,tzinfo=timezone.utc),
        reason=payload.reason.strip(),currency=invoice.currency,subtotal=subtotal,tax_total=tax_total,
        total=total,status="draft",idempotency_key=payload.idempotency_key,created_by=user.id)
    db.add(note);db.flush()
    for source,qty,line_sub,line_tax,line_total in allocations:
        db.add(AccountingCreditNoteLine(organization_id=membership.organization_id,credit_note_id=note.id,
            invoice_line_id=source.id,quantity=qty,subtotal=line_sub,tax_amount=line_tax,total=line_total))
    db.flush()
    lines=[]
    if invoice.invoice_type=="receivable":
        for source,qty,line_sub,line_tax,line_total in allocations:
            lines.append({"account_id":source.account_id,"description":"Credit "+note.credit_note_number+" · "+source.description,
                "debit":line_sub,"credit":Decimal("0")})
            if line_tax:
                lines.append({"account_id":source.tax_account_id,"description":"Output tax credit "+note.credit_note_number,
                    "debit":line_tax,"credit":Decimal("0")})
        lines.append({"account_id":invoice.control_account_id,"description":"Accounts receivable credit "+note.credit_note_number,
            "debit":Decimal("0"),"credit":total})
    else:
        lines.append({"account_id":invoice.control_account_id,"description":"Accounts payable credit "+note.credit_note_number,
            "debit":total,"credit":Decimal("0")})
        for source,qty,line_sub,line_tax,line_total in allocations:
            lines.append({"account_id":source.account_id,"description":"Purchase credit "+note.credit_note_number+" · "+source.description,
                "debit":Decimal("0"),"credit":line_sub})
            if line_tax:
                lines.append({"account_id":source.tax_account_id,"description":"Input tax credit "+note.credit_note_number,
                    "debit":Decimal("0"),"credit":line_tax})
    validate_journal_lines([type("Line",(),line)() for line in lines])
    journal=_accounting_make_journal(db,membership,user,payload.issue_date,note.credit_note_number,
        "Credit note "+note.credit_note_number,lines,invoice.branch_id)
    note.status="posted";note.journal_id=journal.id;note.posted_by=user.id;note.posted_at=datetime.now(timezone.utc)
    invoice.subtotal=Decimal(invoice.subtotal)-subtotal
    invoice.tax_total=Decimal(invoice.tax_total)-tax_total
    invoice.total=Decimal(invoice.total)-total
    invoice.status="paid" if invoice.amount_paid==invoice.total else "partially_paid" if invoice.amount_paid>0 else "posted"
    db.commit()
    audit(db,user.id,membership.organization_id,"accounting.credit_note.posted","accounting_credit_note",note.id,note.credit_note_number)
    return {"id":note.id,"credit_note_number":note.credit_note_number,"status":note.status,
        "subtotal":str(note.subtotal),"tax_total":str(note.tax_total),"total":str(note.total),
        "journal_id":journal.id,"invoice_balance":str(invoice.total-invoice.amount_paid)}


@router.get("/accounting/credit-notes")
def list_accounting_credit_notes(invoice_id:int|None=None,membership=Depends(active_membership),
    db:Session=Depends(get_db),limit:int=Query(default=100,ge=1,le=500)):
    require_permission(membership,"read")
    q=db.query(AccountingCreditNote).filter_by(organization_id=membership.organization_id)
    if invoice_id is not None:q=q.filter(AccountingCreditNote.invoice_id==invoice_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:return []
        q=q.filter((AccountingCreditNote.branch_id==None)|(AccountingCreditNote.branch_id.in_(allowed)))
    rows=q.order_by(AccountingCreditNote.id.desc()).limit(limit).all()
    return [{"id":x.id,"invoice_id":x.invoice_id,"credit_note_number":x.credit_note_number,
        "issue_date":x.issue_date.date().isoformat(),"reason":x.reason,"subtotal":str(x.subtotal),
        "tax_total":str(x.tax_total),"total":str(x.total),"currency":x.currency,"status":x.status,
        "journal_id":x.journal_id} for x in rows]


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


@router.get("/accounting/fiscal-periods")
def list_accounting_periods(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    rows=db.query(AccountingFiscalPeriod).filter_by(organization_id=membership.organization_id).order_by(AccountingFiscalPeriod.start_date).all()
    return [{"id":x.id,"code":x.code,"start_date":x.start_date.date().isoformat(),
        "end_date":x.end_date.date().isoformat(),"status":x.status} for x in rows]


@router.post("/accounting/fiscal-periods",status_code=201)
def create_accounting_period(payload:AccountingFiscalPeriodIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    if payload.end_date<payload.start_date: raise HTTPException(422,"Period end must not precede its start")
    start=datetime.combine(payload.start_date,time.min,tzinfo=timezone.utc)
    end=datetime.combine(payload.end_date,time.max,tzinfo=timezone.utc)
    overlap=db.query(AccountingFiscalPeriod).filter(
        AccountingFiscalPeriod.organization_id==membership.organization_id,
        AccountingFiscalPeriod.start_date<=end,AccountingFiscalPeriod.end_date>=start).first()
    if overlap: raise HTTPException(409,"Fiscal periods cannot overlap")
    row=AccountingFiscalPeriod(organization_id=membership.organization_id,code=payload.code.strip().upper(),
        start_date=start,end_date=end,status="open",created_by=user.id)
    db.add(row)
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Fiscal period code already exists")
    db.refresh(row);audit(db,user.id,membership.organization_id,"accounting.period.created","accounting_period",row.id)
    return {"id":row.id,"code":row.code,"status":row.status}


def _accounting_period_close_check(db, organization_id, period):
    """Return unresolved work that must be cleared before a period is locked."""
    start, end = period.start_date, period.end_date
    draft_invoices = db.query(AccountingInvoice).filter(
        AccountingInvoice.organization_id == organization_id,
        AccountingInvoice.status == "draft",
        AccountingInvoice.issue_date >= start,
        AccountingInvoice.issue_date <= end,
    ).count()
    pending_approvals = db.query(AccountingInvoiceApproval).join(
        AccountingInvoice, AccountingInvoice.id == AccountingInvoiceApproval.invoice_id
    ).filter(
        AccountingInvoiceApproval.organization_id == organization_id,
        AccountingInvoiceApproval.status == "pending",
        AccountingInvoice.organization_id == organization_id,
        AccountingInvoice.issue_date >= start,
        AccountingInvoice.issue_date <= end,
    ).count()
    draft_credit_notes = db.query(AccountingCreditNote).filter(
        AccountingCreditNote.organization_id == organization_id,
        AccountingCreditNote.status == "draft",
        AccountingCreditNote.issue_date >= start,
        AccountingCreditNote.issue_date <= end,
    ).count()
    draft_journals = db.query(AccountingJournal).filter(
        AccountingJournal.organization_id == organization_id,
        AccountingJournal.status == "draft",
        AccountingJournal.entry_date >= start,
        AccountingJournal.entry_date <= end,
    ).count()
    unreconciled_bank_statements = db.query(AccountingBankStatement).filter(
        AccountingBankStatement.organization_id == organization_id,
        AccountingBankStatement.status != "reconciled",
        AccountingBankStatement.start_date <= end,
        AccountingBankStatement.end_date >= start,
    ).count()
    unbalanced_posted_journals = db.query(AccountingJournal.id).join(
        AccountingJournalLine, AccountingJournalLine.journal_id == AccountingJournal.id
    ).filter(
        AccountingJournal.organization_id == organization_id,
        AccountingJournal.status == "posted",
        AccountingJournal.entry_date >= start,
        AccountingJournal.entry_date <= end,
    ).group_by(AccountingJournal.id).having(
        func.coalesce(func.sum(AccountingJournalLine.debit), 0)
        != func.coalesce(func.sum(AccountingJournalLine.credit), 0)
    ).count()
    unposted_procurement_supplier_invoices = db.query(ProcurementSupplierInvoice).filter(
        ProcurementSupplierInvoice.organization_id == organization_id,
        ProcurementSupplierInvoice.status == "matched",
        ProcurementSupplierInvoice.invoice_date >= start,
        ProcurementSupplierInvoice.invoice_date <= end,
    ).count()
    counts = {
        "draft_invoices": draft_invoices,
        "pending_invoice_approvals": pending_approvals,
        "draft_credit_notes": draft_credit_notes,
        "draft_journals": draft_journals,
        "unreconciled_bank_statements": unreconciled_bank_statements,
        "unbalanced_posted_journals": unbalanced_posted_journals,
        "unposted_procurement_supplier_invoices": unposted_procurement_supplier_invoices,
    }
    blockers = [{"code": key, "count": value} for key, value in counts.items() if value]
    return {"period_id": period.id, "period_code": period.code,
        "start_date": start.date().isoformat(), "end_date": end.date().isoformat(),
        "ready_to_close": not blockers, "checks": counts, "blockers": blockers}


@router.get("/accounting/fiscal-periods/{period_id}/close-check")
def accounting_period_close_check(period_id: int, membership=Depends(active_membership),
    db: Session = Depends(get_db)):
    require_permission(membership, "read")
    period = db.query(AccountingFiscalPeriod).filter_by(
        id=period_id, organization_id=membership.organization_id).first()
    if not period:
        raise HTTPException(404, "Fiscal period not found")
    return _accounting_period_close_check(db, membership.organization_id, period)


@router.post("/accounting/fiscal-periods/{period_id}/close")
def close_accounting_period(period_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(AccountingFiscalPeriod).filter_by(
        id=period_id,organization_id=membership.organization_id).with_for_update().first()
    if not row: raise HTTPException(404,"Fiscal period not found")
    if row.status=="closed": raise HTTPException(409,"Fiscal period is already closed")
    close_check = _accounting_period_close_check(db, membership.organization_id, row)
    if not close_check["ready_to_close"]:
        raise HTTPException(409, detail={
            "message": "Fiscal period has unresolved close controls",
            "period_id": row.id,
            "blockers": close_check["blockers"],
            "checks": close_check["checks"],
        })
    row.status="closed";row.closed_by=user.id;row.closed_at=datetime.now(timezone.utc)
    db.commit();audit(db,user.id,membership.organization_id,"accounting.period.closed","accounting_period",row.id)
    return {"id":row.id,"code":row.code,"status":row.status,"closed_at":row.closed_at.isoformat()}


@router.post("/accounting/budgets",status_code=201)
def create_accounting_budget(payload:AccountingBudgetIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    period=db.query(AccountingFiscalPeriod).filter_by(
        id=payload.fiscal_period_id,organization_id=membership.organization_id,status="open").first()
    if not period: raise HTTPException(404,"Open fiscal period not found")
    account_ids={x.account_id for x in payload.lines}
    accounts=_accounting_get_accounts(db,membership.organization_id,account_ids)
    if any(x.account_type not in ("expense","revenue") for x in accounts.values()):
        raise HTTPException(422,"Budgets can only target revenue or expense accounts")
    for item in payload.lines:
        if item.branch_id: _crm_branch_check(db,membership,item.branch_id)
    row=AccountingBudget(organization_id=membership.organization_id,fiscal_period_id=period.id,
        name=payload.name.strip(),status="draft",created_by=user.id)
    db.add(row);db.flush()
    for item in payload.lines:
        db.add(AccountingBudgetLine(organization_id=membership.organization_id,budget_id=row.id,
            account_id=item.account_id,branch_id=item.branch_id,amount=item.amount))
    db.commit();db.refresh(row)
    audit(db,user.id,membership.organization_id,"accounting.budget.created","accounting_budget",row.id)
    return {"id":row.id,"name":row.name,"status":row.status}


@router.post("/accounting/budgets/{budget_id}/approve")
def approve_accounting_budget(budget_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(AccountingBudget).filter_by(
        id=budget_id,organization_id=membership.organization_id).with_for_update().first()
    if not row: raise HTTPException(404,"Budget not found")
    if row.status!="draft": raise HTTPException(409,"Only draft budgets can be approved")
    period=db.query(AccountingFiscalPeriod).filter_by(
        id=row.fiscal_period_id,organization_id=membership.organization_id,status="open").first()
    if not period: raise HTTPException(409,"Budget fiscal period is closed")
    row.status="approved";row.approved_by=user.id;row.approved_at=datetime.now(timezone.utc)
    db.commit();audit(db,user.id,membership.organization_id,"accounting.budget.approved","accounting_budget",row.id)
    return {"id":row.id,"status":row.status}


@router.get("/accounting/budgets/{budget_id}/performance")
def accounting_budget_performance(budget_id:int,membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    budget=db.query(AccountingBudget).filter_by(
        id=budget_id,organization_id=membership.organization_id,status="approved").first()
    if not budget: raise HTTPException(404,"Approved budget not found")
    period=db.query(AccountingFiscalPeriod).filter_by(
        id=budget.fiscal_period_id,organization_id=membership.organization_id).first()
    if not period: raise HTTPException(404,"Budget period not found")
    lines=db.query(AccountingBudgetLine,AccountingAccount).join(
        AccountingAccount,AccountingAccount.id==AccountingBudgetLine.account_id).filter(
        AccountingBudgetLine.organization_id==membership.organization_id,
        AccountingBudgetLine.budget_id==budget.id).all()
    output=[]
    for item,account in lines:
        q=db.query(func.coalesce(func.sum(AccountingJournalLine.debit-AccountingJournalLine.credit),0)).join(
            AccountingJournal,AccountingJournal.id==AccountingJournalLine.journal_id).filter(
            AccountingJournalLine.organization_id==membership.organization_id,
            AccountingJournalLine.account_id==item.account_id,
            AccountingJournal.entry_date>=period.start_date,AccountingJournal.entry_date<=period.end_date)
        if item.branch_id is not None:
            q=q.filter(AccountingJournalLine.branch_id==item.branch_id)
        allowed=branch_scope_ids(membership)
        if allowed is not None:
            if item.branch_id is not None and item.branch_id not in allowed: continue
            if item.branch_id is None: q=q.filter((AccountingJournalLine.branch_id==None)|(AccountingJournalLine.branch_id.in_(allowed)))
        actual=Decimal(str(q.scalar() or 0))
        if account.account_type=="revenue": actual=-actual
        output.append({"account_id":account.id,"code":account.code,"name":account.name,
            "branch_id":item.branch_id,"budget":str(item.amount),"actual":str(actual),
            "variance":str(Decimal(item.amount)-actual)})
    return {"budget_id":budget.id,"period":period.code,"status":budget.status,"lines":output}


@router.post("/accounting/fixed-assets",status_code=201)
def create_accounting_fixed_asset(payload:AccountingFixedAssetIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    if payload.salvage_value>=payload.cost: raise HTTPException(422,"Salvage value must be less than asset cost")
    if payload.branch_id: _crm_branch_check(db,membership,payload.branch_id)
    accounts=_accounting_get_accounts(db,membership.organization_id,
        {payload.asset_account_id,payload.accumulated_depreciation_account_id,
         payload.depreciation_expense_account_id,payload.payment_account_id})
    if accounts[payload.asset_account_id].account_type!="asset": raise HTTPException(422,"Asset account must be an asset")
    if accounts[payload.accumulated_depreciation_account_id].account_type!="asset": raise HTTPException(422,"Accumulated depreciation account must be an asset")
    if accounts[payload.depreciation_expense_account_id].account_type!="expense": raise HTTPException(422,"Depreciation expense account must be an expense")
    if accounts[payload.payment_account_id].account_type!="asset": raise HTTPException(422,"Acquisition payment account must be an asset")
    row=AccountingFixedAsset(organization_id=membership.organization_id,branch_id=payload.branch_id,
        asset_code=payload.asset_code.strip().upper(),name=payload.name.strip(),
        acquisition_date=datetime.combine(payload.acquisition_date,time.min,tzinfo=timezone.utc),
        cost=payload.cost,salvage_value=payload.salvage_value,useful_life_months=payload.useful_life_months,
        accumulated_depreciation=Decimal("0"),asset_account_id=payload.asset_account_id,
        accumulated_depreciation_account_id=payload.accumulated_depreciation_account_id,
        depreciation_expense_account_id=payload.depreciation_expense_account_id,
        status="active",created_by=user.id)
    db.add(row)
    journal=_accounting_make_journal(db,membership,user,payload.acquisition_date,
        payload.asset_code,"Fixed asset acquisition "+payload.name,[
            {"account_id":payload.asset_account_id,"description":"Acquire "+payload.name,"debit":payload.cost,"credit":Decimal("0")},
            {"account_id":payload.payment_account_id,"description":"Asset payment "+payload.name,"debit":Decimal("0"),"credit":payload.cost}],payload.branch_id)
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Asset code already exists or acquisition conflicts")
    db.refresh(row);audit(db,user.id,membership.organization_id,"accounting.fixed_asset.created","fixed_asset",row.id)
    return {"id":row.id,"asset_code":row.asset_code,"status":row.status,"acquisition_journal_id":journal.id}


@router.get("/accounting/fixed-assets")
def list_accounting_fixed_assets(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    q=db.query(AccountingFixedAsset).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:return []
        q=q.filter((AccountingFixedAsset.branch_id==None)|(AccountingFixedAsset.branch_id.in_(allowed)))
    return [{"id":x.id,"asset_code":x.asset_code,"name":x.name,"cost":str(x.cost),
        "salvage_value":str(x.salvage_value),"useful_life_months":x.useful_life_months,
        "accumulated_depreciation":str(x.accumulated_depreciation),
        "net_book_value":str(x.cost-x.accumulated_depreciation),"status":x.status,
        "branch_id":x.branch_id} for x in q.order_by(AccountingFixedAsset.asset_code).all()]


@router.post("/accounting/fixed-assets/{asset_id}/depreciation")
def depreciate_accounting_fixed_asset(asset_id:int,payload:AccountingDepreciationIn,
    membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    period_date=payload.period_date.replace(day=1)
    _accounting_assert_period_open(db,membership.organization_id,period_date)
    duplicate=db.query(AccountingDepreciationEntry).filter_by(
        organization_id=membership.organization_id,idempotency_key=payload.idempotency_key).first()
    if duplicate:
        if duplicate.asset_id==asset_id and duplicate.period_date.date()==period_date:
            return {"id":duplicate.id,"status":"already_applied","journal_id":duplicate.journal_id}
        raise HTTPException(409,"Depreciation idempotency key already used")
    asset=db.query(AccountingFixedAsset).filter_by(
        id=asset_id,organization_id=membership.organization_id,status="active").with_for_update().first()
    if not asset or (asset.branch_id and not can_access_branch(membership,asset.branch_id)):
        raise HTTPException(404,"Fixed asset not found")
    if period_date<asset.acquisition_date.date(): raise HTTPException(422,"Depreciation cannot precede acquisition")
    start=datetime.combine(period_date,time.min,tzinfo=timezone.utc)
    next_month=date(period_date.year+1,1,1) if period_date.month==12 else date(period_date.year,period_date.month+1,1)
    end=datetime.combine(next_month,time.min,tzinfo=timezone.utc)
    existing=db.query(AccountingDepreciationEntry).filter(
        AccountingDepreciationEntry.organization_id==membership.organization_id,
        AccountingDepreciationEntry.asset_id==asset.id,
        AccountingDepreciationEntry.period_date>=start,
        AccountingDepreciationEntry.period_date<end).first()
    if existing: raise HTTPException(409,"Depreciation has already been posted for this asset and month")
    depreciable=Decimal(asset.cost)-Decimal(asset.salvage_value)
    remaining=depreciable-Decimal(asset.accumulated_depreciation)
    if remaining<=0: raise HTTPException(409,"Asset is fully depreciated")
    monthly=(depreciable/Decimal(asset.useful_life_months)).quantize(Decimal("0.01"))
    amount=min(monthly,remaining)
    journal=_accounting_make_journal(db,membership,user,period_date,
        asset.asset_code+"-"+period_date.strftime("%Y%m"),
        "Monthly straight-line depreciation "+asset.name,[
            {"account_id":asset.depreciation_expense_account_id,"description":"Depreciation "+asset.name,
             "debit":amount,"credit":Decimal("0"),"branch_id":asset.branch_id},
            {"account_id":asset.accumulated_depreciation_account_id,"description":"Accumulated depreciation "+asset.name,
             "debit":Decimal("0"),"credit":amount,"branch_id":asset.branch_id}],asset.branch_id)
    asset.accumulated_depreciation=Decimal(asset.accumulated_depreciation)+amount
    entry=AccountingDepreciationEntry(organization_id=membership.organization_id,asset_id=asset.id,
        period_date=start,amount=amount,journal_id=journal.id,idempotency_key=payload.idempotency_key,created_by=user.id)
    db.add(entry)
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Depreciation conflicts with a concurrent posting")
    audit(db,user.id,membership.organization_id,"accounting.asset.depreciated","fixed_asset",asset.id,str(amount))
    return {"id":entry.id,"amount":str(amount),"accumulated_depreciation":str(asset.accumulated_depreciation),
        "net_book_value":str(Decimal(asset.cost)-Decimal(asset.accumulated_depreciation)),"journal_id":journal.id}


@router.get("/accounting/financial-statements")
def accounting_financial_statements(start_date:date,end_date:date,
    membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    if end_date<start_date: raise HTTPException(422,"End date must not precede start date")
    end=datetime.combine(end_date,time.max,tzinfo=timezone.utc)
    start=datetime.combine(start_date,time.min,tzinfo=timezone.utc)
    q=db.query(AccountingAccount,AccountingJournalLine,AccountingJournal).join(
        AccountingJournalLine,AccountingJournalLine.account_id==AccountingAccount.id).join(
        AccountingJournal,AccountingJournal.id==AccountingJournalLine.journal_id).filter(
        AccountingAccount.organization_id==membership.organization_id,
        AccountingJournalLine.organization_id==membership.organization_id,
        AccountingJournal.organization_id==membership.organization_id,
        AccountingJournal.status=="posted",AccountingJournal.entry_date<=end)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:q=q.filter(AccountingJournalLine.branch_id==None)
        else:q=q.filter((AccountingJournalLine.branch_id==None)|(AccountingJournalLine.branch_id.in_(allowed)))
    rows=q.all()
    pnl=[];balance=[];revenues=Decimal("0");expenses=Decimal("0")
    assets=Decimal("0");liabilities=Decimal("0");equity=Decimal("0");cumulative_profit=Decimal("0")
    for account,line,journal in rows:
        debit=Decimal(line.debit);credit=Decimal(line.credit)
        if account.account_type=="asset": assets+=debit-credit
        elif account.account_type=="liability": liabilities+=credit-debit
        elif account.account_type=="equity": equity+=credit-debit
        elif account.account_type=="revenue": cumulative_profit+=credit-debit
        elif account.account_type=="expense": cumulative_profit-=debit-credit
        if start<=journal.entry_date<=end and account.account_type in ("revenue","expense"):
            period_value=credit-debit if account.account_type=="revenue" else debit-credit
            if account.account_type=="revenue":revenues+=period_value
            else:expenses+=period_value
            pnl.append({"account_id":account.id,"code":account.code,"name":account.name,
                "account_type":account.account_type,"amount":str(period_value)})
    for account_type,amount in (("assets",assets),("liabilities",liabilities),("equity",equity),("retained_earnings",cumulative_profit)):
        balance.append({"category":account_type,"amount":str(amount)})
    net_income=revenues-expenses
    return {"period":{"start":start_date.isoformat(),"end":end_date.isoformat()},
        "profit_and_loss":{"revenue":str(revenues),"expenses":str(expenses),"net_income":str(net_income),"lines":pnl},
        "balance_sheet":{"lines":balance,"total_assets":str(assets),
            "total_liabilities_and_equity":str(liabilities+equity+cumulative_profit),
            "balanced":assets==liabilities+equity+cumulative_profit}}


@router.post("/accounting/bank-statements",status_code=201)
def import_accounting_bank_statement(payload:AccountingBankStatementIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    if payload.end_date<payload.start_date: raise HTTPException(422,"Statement end date must not precede start date")
    if payload.branch_id: _crm_branch_check(db,membership,payload.branch_id)
    elif branch_scope_ids(membership) is not None:
        raise HTTPException(403,"Branch-scoped users must select an authorized statement branch")
    account=_accounting_get_accounts(db,membership.organization_id,{payload.bank_account_id})[payload.bank_account_id]
    if account.account_type!="asset": raise HTTPException(422,"Bank statement must use an asset account")
    if sum((x.amount for x in payload.lines),Decimal("0"))+payload.opening_balance!=payload.closing_balance:
        raise HTTPException(422,"Opening balance plus statement movements must equal closing balance")
    for item in payload.lines:
        if item.transaction_date<payload.start_date or item.transaction_date>payload.end_date:
            raise HTTPException(422,"Statement transaction date falls outside the statement period")
    statement=AccountingBankStatement(organization_id=membership.organization_id,
        bank_account_id=payload.bank_account_id,branch_id=payload.branch_id,
        statement_reference=payload.statement_reference.strip(),start_date=datetime.combine(payload.start_date,time.min,tzinfo=timezone.utc),
        end_date=datetime.combine(payload.end_date,time.max,tzinfo=timezone.utc),
        opening_balance=payload.opening_balance,closing_balance=payload.closing_balance,
        status="draft",created_by=user.id)
    db.add(statement);db.flush()
    for index,item in enumerate(payload.lines,1):
        db.add(AccountingBankStatementLine(organization_id=membership.organization_id,
            statement_id=statement.id,line_number=index,
            transaction_date=datetime.combine(item.transaction_date,time.min,tzinfo=timezone.utc),
            description=item.description.strip(),reference=item.reference,amount=item.amount))
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Statement reference already exists")
    db.refresh(statement);audit(db,user.id,membership.organization_id,"accounting.bank_statement.imported","bank_statement",statement.id)
    return {"id":statement.id,"statement_reference":statement.statement_reference,
        "line_count":len(payload.lines),"status":statement.status}


@router.get("/accounting/bank-statements")
def list_accounting_bank_statements(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    q=db.query(AccountingBankStatement).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:return []
        q=q.filter(AccountingBankStatement.branch_id.in_(allowed))
    rows=q.order_by(AccountingBankStatement.id.desc()).limit(200).all()
    result=[]
    for x in rows:
        total=db.query(AccountingBankStatementLine).filter_by(
            organization_id=membership.organization_id,statement_id=x.id).count()
        matched=db.query(AccountingBankStatementLine).filter(
            AccountingBankStatementLine.organization_id==membership.organization_id,
            AccountingBankStatementLine.statement_id==x.id,
            AccountingBankStatementLine.matched_journal_line_id.isnot(None)).count()
        result.append({"id":x.id,"statement_reference":x.statement_reference,
            "bank_account_id":x.bank_account_id,"start_date":x.start_date.date().isoformat(),
            "end_date":x.end_date.date().isoformat(),"opening_balance":str(x.opening_balance),
            "closing_balance":str(x.closing_balance),"line_count":total,"matched_count":matched,"status":x.status})
    return result


@router.get("/accounting/bank-statements/{statement_id}")
def get_accounting_bank_statement(statement_id:int,membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    statement=db.query(AccountingBankStatement).filter_by(
        id=statement_id,organization_id=membership.organization_id).first()
    if not statement or (statement.branch_id is None and branch_scope_ids(membership) is not None) or (statement.branch_id and not can_access_branch(membership,statement.branch_id)):
        raise HTTPException(404,"Bank statement not found")
    lines=db.query(AccountingBankStatementLine).filter_by(
        organization_id=membership.organization_id,statement_id=statement.id).order_by(
        AccountingBankStatementLine.line_number).all()
    return {"id":statement.id,"statement_reference":statement.statement_reference,
        "status":statement.status,"bank_account_id":statement.bank_account_id,
        "start_date":statement.start_date.date().isoformat(),"end_date":statement.end_date.date().isoformat(),
        "opening_balance":str(statement.opening_balance),"closing_balance":str(statement.closing_balance),
        "lines":[{"id":x.id,"line_number":x.line_number,"transaction_date":x.transaction_date.date().isoformat(),
            "description":x.description,"reference":x.reference,"amount":str(x.amount),
            "matched_journal_line_id":x.matched_journal_line_id} for x in lines]}


@router.post("/accounting/bank-statements/{statement_id}/match")
def match_accounting_bank_statement_line(statement_id:int,payload:AccountingBankMatchIn,
    membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    statement=db.query(AccountingBankStatement).filter_by(
        id=statement_id,organization_id=membership.organization_id,status="draft").with_for_update().first()
    if not statement or (statement.branch_id is None and branch_scope_ids(membership) is not None) or (statement.branch_id and not can_access_branch(membership,statement.branch_id)):
        raise HTTPException(404,"Draft bank statement not found")
    line=db.query(AccountingBankStatementLine).filter_by(
        id=payload.statement_line_id,statement_id=statement.id,
        organization_id=membership.organization_id).with_for_update().first()
    if not line: raise HTTPException(404,"Statement line not found")
    if line.matched_journal_line_id: raise HTTPException(409,"Statement line is already matched")
    journal_line=db.query(AccountingJournalLine).join(
        AccountingJournal,AccountingJournal.id==AccountingJournalLine.journal_id).filter(
        AccountingJournalLine.id==payload.journal_line_id,
        AccountingJournalLine.organization_id==membership.organization_id,
        AccountingJournalLine.account_id==statement.bank_account_id,
        AccountingJournal.organization_id==membership.organization_id,
        AccountingJournal.status=="posted",
        AccountingJournal.entry_date>=statement.start_date,
        AccountingJournal.entry_date<=statement.end_date).first()
    if not journal_line: raise HTTPException(404,"Matching posted bank ledger line not found in this statement period")
    if statement.branch_id is not None and journal_line.branch_id!=statement.branch_id:
        raise HTTPException(422,"Journal line belongs to a different branch")
    if not can_access_branch(membership,journal_line.branch_id):
        raise HTTPException(404,"Matching journal line not found")
    movement=Decimal(journal_line.debit)-Decimal(journal_line.credit)
    if movement!=Decimal(line.amount):
        raise HTTPException(422,"Statement amount does not equal the bank ledger movement")
    already=db.query(AccountingBankStatementLine).filter_by(
        organization_id=membership.organization_id,matched_journal_line_id=journal_line.id).first()
    if already: raise HTTPException(409,"Bank ledger line is already matched to another statement line")
    line.matched_journal_line_id=journal_line.id;line.matched_by=user.id;line.matched_at=datetime.now(timezone.utc)
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Bank ledger line was matched concurrently")
    audit(db,user.id,membership.organization_id,"accounting.bank_statement.line_matched",
        "bank_statement_line",line.id,str(journal_line.id))
    return {"statement_line_id":line.id,"journal_line_id":journal_line.id,"status":"matched"}


@router.post("/accounting/bank-statements/{statement_id}/reconcile")
def reconcile_accounting_bank_statement(statement_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    statement=db.query(AccountingBankStatement).filter_by(
        id=statement_id,organization_id=membership.organization_id,status="draft").with_for_update().first()
    if not statement or (statement.branch_id and not can_access_branch(membership,statement.branch_id)):
        raise HTTPException(404,"Draft bank statement not found")
    unmatched=db.query(AccountingBankStatementLine).filter_by(
        organization_id=membership.organization_id,statement_id=statement.id,
        matched_journal_line_id=None).count()
    if unmatched: raise HTTPException(409,f"{unmatched} statement lines remain unmatched")
    q=db.query(func.coalesce(func.sum(AccountingJournalLine.debit-AccountingJournalLine.credit),0)).join(
        AccountingJournal,AccountingJournal.id==AccountingJournalLine.journal_id).filter(
        AccountingJournalLine.organization_id==membership.organization_id,
        AccountingJournalLine.account_id==statement.bank_account_id,
        AccountingJournal.organization_id==membership.organization_id,
        AccountingJournal.status=="posted")
    if statement.branch_id is not None:
        q=q.filter(AccountingJournalLine.branch_id==statement.branch_id)
    else:
        allowed=branch_scope_ids(membership)
        if allowed is not None:
            if not allowed: raise HTTPException(403,"No branch access is assigned")
            q=q.filter((AccountingJournalLine.branch_id==None)|(AccountingJournalLine.branch_id.in_(allowed)))
    opening=Decimal(str(q.filter(AccountingJournal.entry_date<statement.start_date).scalar() or 0))
    closing=Decimal(str(q.filter(AccountingJournal.entry_date<=statement.end_date).scalar() or 0))
    if opening!=Decimal(statement.opening_balance):
        raise HTTPException(409,f"Opening balance does not agree with bank ledger: ledger {opening}, statement {statement.opening_balance}")
    if closing!=Decimal(statement.closing_balance):
        raise HTTPException(409,f"Closing balance does not agree with bank ledger: ledger {closing}, statement {statement.closing_balance}")
    statement.status="reconciled";statement.reconciled_by=user.id;statement.reconciled_at=datetime.now(timezone.utc)
    db.commit();audit(db,user.id,membership.organization_id,"accounting.bank_statement.reconciled","bank_statement",statement.id)
    return {"id":statement.id,"status":statement.status,"opening_balance":str(opening),
        "closing_balance":str(closing),"reconciled_at":statement.reconciled_at.isoformat()}


@router.post("/crm/quotes",status_code=201)
def create_crm_quote(payload:CRMQuoteIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    if payload.valid_until<payload.issue_date: raise HTTPException(422,"Quote validity cannot end before issue date")
    organization=db.query(Organization).filter_by(id=membership.organization_id,is_active=True).first()
    if not organization or payload.currency!=organization.currency:
        raise HTTPException(422,"Quote currency must match the organization's configured base currency")
    _crm_branch_check(db,membership,payload.branch_id)
    contact=db.query(CRMContact).filter_by(
        id=payload.contact_id,organization_id=membership.organization_id).first()
    if not contact or not can_access_branch(membership,contact.branch_id):
        raise HTTPException(404,"Customer contact not found")
    if payload.branch_id!=contact.branch_id:
        raise HTTPException(422,"Quote and customer contact must belong to the same branch")
    lead=None
    if payload.lead_id:
        lead=db.query(CRMLead).filter_by(
            id=payload.lead_id,organization_id=membership.organization_id).first()
        if not lead or not can_access_branch(membership,lead.branch_id):
            raise HTTPException(404,"Sales lead not found")
        if lead.contact_id and lead.contact_id!=contact.id:
            raise HTTPException(422,"Quote contact must match the selected lead contact")
        if payload.branch_id!=lead.branch_id:
            raise HTTPException(422,"Quote and lead must belong to the same branch")
    subtotal=Decimal("0.00");tax_total=Decimal("0.00");computed=[]
    for item in payload.lines:
        line_sub=(item.quantity*item.unit_price).quantize(Decimal("0.01"))
        line_tax=(line_sub*item.tax_rate/Decimal("100")).quantize(Decimal("0.01"))
        line_total=line_sub+line_tax
        subtotal+=line_sub;tax_total+=line_tax;computed.append((item,line_sub,line_tax,line_total))
    total=subtotal+tax_total
    if total<=0: raise HTTPException(422,"Quote total must be greater than zero")
    row=CRMQuote(organization_id=membership.organization_id,branch_id=payload.branch_id,
        contact_id=contact.id,lead_id=lead.id if lead else None,quote_number=payload.quote_number.strip().upper(),
        currency=payload.currency,issue_date=datetime.combine(payload.issue_date,time.min,tzinfo=timezone.utc),
        valid_until=datetime.combine(payload.valid_until,time.max,tzinfo=timezone.utc),
        subtotal=subtotal,tax_total=tax_total,total=total,status="draft",created_by=user.id)
    db.add(row);db.flush()
    for item,line_sub,line_tax,line_total in computed:
        db.add(CRMQuoteLine(organization_id=membership.organization_id,quote_id=row.id,
            description=item.description.strip(),quantity=item.quantity,unit_price=item.unit_price,
            tax_rate=item.tax_rate,subtotal=line_sub,tax_amount=line_tax,total=line_total))
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Quote number already exists in this organization")
    db.refresh(row);audit(db,user.id,membership.organization_id,"crm.quote.created","crm_quote",row.id)
    return {"id":row.id,"quote_number":row.quote_number,"subtotal":str(row.subtotal),
        "tax_total":str(row.tax_total),"total":str(row.total),"status":row.status}


@router.get("/crm/quotes")
def list_crm_quotes(status:str|None=None,membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    q=db.query(CRMQuote).filter_by(organization_id=membership.organization_id)
    if status:
        if status not in ("draft","issued","accepted","rejected","expired"): raise HTTPException(422,"Invalid quote status")
        q=q.filter(CRMQuote.status==status)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:return []
        q=q.filter(CRMQuote.branch_id.in_(allowed))
    rows=q.order_by(CRMQuote.id.desc()).limit(200).all()
    return [{"id":x.id,"quote_number":x.quote_number,"contact_id":x.contact_id,"lead_id":x.lead_id,
        "currency":x.currency,"total":str(x.total),"valid_until":x.valid_until.date().isoformat(),
        "status":x.status,"branch_id":x.branch_id} for x in rows]


@router.get("/crm/quotes/{quote_id}")
def get_crm_quote(quote_id:int,membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    row=db.query(CRMQuote).filter_by(id=quote_id,organization_id=membership.organization_id).first()
    if not row or not can_access_branch(membership,row.branch_id): raise HTTPException(404,"Quote not found")
    lines=db.query(CRMQuoteLine).filter_by(
        quote_id=row.id,organization_id=membership.organization_id).order_by(CRMQuoteLine.id).all()
    return {"id":row.id,"quote_number":row.quote_number,"contact_id":row.contact_id,"lead_id":row.lead_id,
        "currency":row.currency,"issue_date":row.issue_date.date().isoformat(),
        "valid_until":row.valid_until.date().isoformat(),"subtotal":str(row.subtotal),
        "tax_total":str(row.tax_total),"total":str(row.total),"status":row.status,
        "lines":[{"id":x.id,"description":x.description,"quantity":str(x.quantity),
            "unit_price":str(x.unit_price),"tax_rate":str(x.tax_rate),
            "subtotal":str(x.subtotal),"tax_amount":str(x.tax_amount),"total":str(x.total)} for x in lines]}


@router.post("/crm/quotes/{quote_id}/issue")
def issue_crm_quote(quote_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"update")
    row=db.query(CRMQuote).filter_by(
        id=quote_id,organization_id=membership.organization_id).with_for_update().first()
    if not row or not can_access_branch(membership,row.branch_id): raise HTTPException(404,"Quote not found")
    if row.status!="draft": raise HTTPException(409,"Only draft quotes can be issued")
    if row.valid_until.date()<datetime.now(timezone.utc).date():
        row.status="expired";db.commit()
        raise HTTPException(409,"Quote validity has expired")
    row.status="issued";row.issued_at=datetime.now(timezone.utc)
    db.commit();audit(db,user.id,membership.organization_id,"crm.quote.issued","crm_quote",row.id)
    return {"id":row.id,"status":row.status,"issued_at":row.issued_at.isoformat()}


@router.post("/crm/quotes/{quote_id}/accept")
def accept_crm_quote(quote_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"update")
    row=db.query(CRMQuote).filter_by(
        id=quote_id,organization_id=membership.organization_id).with_for_update().first()
    if not row or not can_access_branch(membership,row.branch_id): raise HTTPException(404,"Quote not found")
    if row.status!="issued": raise HTTPException(409,"Only issued quotes can be accepted")
    if row.valid_until.date()<datetime.now(timezone.utc).date():
        row.status="expired";db.commit()
        raise HTTPException(409,"Quote validity has expired")
    row.status="accepted";row.accepted_at=datetime.now(timezone.utc)
    lead=db.query(CRMLead).filter_by(id=row.lead_id,organization_id=membership.organization_id).first() if row.lead_id else None
    if lead and lead.source_campaign_id:
        db.add(CRMCampaignAttribution(organization_id=membership.organization_id,campaign_id=lead.source_campaign_id,
            contact_id=row.contact_id,lead_id=lead.id,event_type="quote_accepted",revenue_amount=Decimal("0"),
            currency=row.currency,idempotency_key="quote-accepted-%s"%row.id,occurred_at=row.accepted_at,created_by=user.id))
    db.commit();audit(db,user.id,membership.organization_id,"crm.quote.accepted","crm_quote",row.id)
    return {"id":row.id,"status":row.status,"accepted_at":row.accepted_at.isoformat()}


@router.post("/crm/quotes/{quote_id}/reject")
def reject_crm_quote(quote_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"update")
    row=db.query(CRMQuote).filter_by(
        id=quote_id,organization_id=membership.organization_id).with_for_update().first()
    if not row or not can_access_branch(membership,row.branch_id): raise HTTPException(404,"Quote not found")
    if row.status!="issued": raise HTTPException(409,"Only issued quotes can be rejected")
    row.status="rejected";row.rejected_at=datetime.now(timezone.utc)
    db.commit();audit(db,user.id,membership.organization_id,"crm.quote.rejected","crm_quote",row.id)
    return {"id":row.id,"status":row.status}



@router.post("/crm/quotes/{quote_id}/convert-to-order", status_code=201)
def convert_crm_quote_to_order(quote_id: int, payload: CRMQuoteConvertIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    """Convert an accepted quote once; conversion creates an order, not stock or an invoice."""
    require_permission(membership, "update")
    quote=db.query(CRMQuote).filter_by(
        id=quote_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not quote or not can_access_branch(membership, quote.branch_id):
        raise HTTPException(404, "Quote not found")
    existing=db.query(CRMSalesOrder).filter_by(
        organization_id=membership.organization_id, quote_id=quote.id
    ).first()
    if existing:
        return {"id":existing.id,"order_number":existing.order_number,
            "quote_id":quote.id,"status":existing.status,"already_converted":True}
    if quote.status != "accepted":
        raise HTTPException(409, "Only accepted quotes can be converted to sales orders")
    if quote.valid_until.date() < datetime.now(timezone.utc).date():
        raise HTTPException(409, "Expired quotes cannot be converted")
    order_number=(payload.order_number or f"SO-{quote.quote_number}").strip().upper()
    lines=db.query(CRMQuoteLine).filter_by(
        organization_id=membership.organization_id, quote_id=quote.id
    ).order_by(CRMQuoteLine.id).all()
    if not lines:
        raise HTTPException(409, "Accepted quote has no line items")
    order=CRMSalesOrder(
        organization_id=membership.organization_id, branch_id=quote.branch_id,
        quote_id=quote.id, contact_id=quote.contact_id, lead_id=quote.lead_id,
        order_number=order_number, currency=quote.currency,
        subtotal=quote.subtotal, tax_total=quote.tax_total, total=quote.total,
        status="confirmed", confirmed_at=datetime.now(timezone.utc), created_by=user.id,
    )
    db.add(order)
    try:
        db.flush()
        for line in lines:
            db.add(CRMSalesOrderLine(
                organization_id=membership.organization_id, sales_order_id=order.id,
                quote_line_id=line.id, description=line.description,
                quantity=line.quantity, unit_price=line.unit_price, tax_rate=line.tax_rate,
                subtotal=line.subtotal, tax_amount=line.tax_amount, total=line.total,
            ))
        lead=db.query(CRMLead).filter_by(id=quote.lead_id,organization_id=membership.organization_id).first() if quote.lead_id else None
        if lead and lead.source_campaign_id:
            db.add(CRMCampaignAttribution(organization_id=membership.organization_id,campaign_id=lead.source_campaign_id,
                contact_id=order.contact_id,lead_id=lead.id,sales_order_id=order.id,event_type="sales_order_confirmed",
                revenue_amount=Decimal("0"),currency=order.currency,idempotency_key="order-confirmed-%s"%order.id,
                occurred_at=order.confirmed_at,created_by=user.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        existing=db.query(CRMSalesOrder).filter_by(
            organization_id=membership.organization_id, quote_id=quote.id
        ).first()
        if existing:
            return {"id":existing.id,"order_number":existing.order_number,
                "quote_id":quote.id,"status":existing.status,"already_converted":True}
        raise HTTPException(409, "Sales order number already exists in this organization")
    db.refresh(order)
    audit(db,user.id,membership.organization_id,"crm.quote.converted_to_order",
          "crm_sales_order",order.id,f"quote:{quote.id};order:{order.order_number}")
    return {"id":order.id,"order_number":order.order_number,"quote_id":quote.id,
            "status":order.status,"currency":order.currency,"total":str(order.total),
            "already_converted":False}


@router.get("/crm/orders")
def list_crm_sales_orders(membership=Depends(active_membership), db: Session=Depends(get_db),
                          limit: int=Query(default=100, ge=1, le=500)):
    require_permission(membership,"read")
    q=db.query(CRMSalesOrder).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed: return []
        q=q.filter(CRMSalesOrder.branch_id.in_(allowed))
    rows=q.order_by(CRMSalesOrder.id.desc()).limit(limit).all()
    return [{"id":x.id,"order_number":x.order_number,"quote_id":x.quote_id,
        "contact_id":x.contact_id,"lead_id":x.lead_id,"currency":x.currency,
        "total":str(x.total),"status":x.status,"confirmed_at":x.confirmed_at.isoformat(),
        "branch_id":x.branch_id} for x in rows]


@router.get("/crm/orders/{order_id}")
def get_crm_sales_order(order_id: int, membership=Depends(active_membership),
                        db: Session=Depends(get_db)):
    require_permission(membership,"read")
    order=db.query(CRMSalesOrder).filter_by(
        id=order_id, organization_id=membership.organization_id
    ).first()
    if not order or not can_access_branch(membership,order.branch_id):
        raise HTTPException(404,"Sales order not found")
    lines=db.query(CRMSalesOrderLine).filter_by(
        organization_id=membership.organization_id,sales_order_id=order.id
    ).order_by(CRMSalesOrderLine.id).all()
    return {"id":order.id,"order_number":order.order_number,"quote_id":order.quote_id,
        "contact_id":order.contact_id,"lead_id":order.lead_id,"currency":order.currency,
        "subtotal":str(order.subtotal),"tax_total":str(order.tax_total),"total":str(order.total),
        "status":order.status,"confirmed_at":order.confirmed_at.isoformat(),
        "lines":[{"id":x.id,"quote_line_id":x.quote_line_id,"description":x.description,
            "quantity":str(x.quantity),"unit_price":str(x.unit_price),"tax_rate":str(x.tax_rate),
            "subtotal":str(x.subtotal),"tax_amount":str(x.tax_amount),"total":str(x.total)}
            for x in lines]}



@router.post("/crm/contacts/{contact_id}/consents", status_code=201)
def record_crm_contact_consent(contact_id: int, payload: CRMContactConsentIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership,"create")
    contact=db.query(CRMContact).filter_by(
        id=contact_id,organization_id=membership.organization_id
    ).first()
    if not contact or not can_access_branch(membership,contact.branch_id):
        raise HTTPException(404,"Contact not found")
    if payload.expires_at and payload.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(422,"Consent expiry must be in the future")
    event=CRMContactConsent(
        organization_id=membership.organization_id,contact_id=contact.id,
        channel=payload.channel,purpose=payload.purpose,decision=payload.decision,
        source=payload.source,recorded_by=user.id,expires_at=payload.expires_at,
    )
    db.add(event);db.commit();db.refresh(event)
    audit(db,user.id,membership.organization_id,"crm.contact.consent_recorded",
          "crm_contact_consent",event.id,
          f"contact:{contact.id};channel:{event.channel};decision:{event.decision};source:{event.source}")
    return {"id":event.id,"contact_id":contact.id,"channel":event.channel,
        "purpose":event.purpose,"decision":event.decision,
        "recorded_at":event.recorded_at.isoformat(),
        "expires_at":event.expires_at.isoformat() if event.expires_at else None}


@router.get("/crm/contacts/{contact_id}/consents")
def list_crm_contact_consents(contact_id: int, membership=Depends(active_membership),
                              db: Session=Depends(get_db)):
    require_permission(membership,"read")
    contact=db.query(CRMContact).filter_by(
        id=contact_id,organization_id=membership.organization_id
    ).first()
    if not contact or not can_access_branch(membership,contact.branch_id):
        raise HTTPException(404,"Contact not found")
    rows=db.query(CRMContactConsent).filter_by(
        organization_id=membership.organization_id,contact_id=contact.id
    ).order_by(CRMContactConsent.recorded_at.desc(),CRMContactConsent.id.desc()).all()
    return [{"id":x.id,"channel":x.channel,"purpose":x.purpose,"decision":x.decision,
        "source":x.source,"recorded_at":x.recorded_at.isoformat(),
        "expires_at":x.expires_at.isoformat() if x.expires_at else None} for x in rows]


@router.post("/crm/campaigns",status_code=201)
def create_crm_campaign(payload: CRMCampaignIn,membership=Depends(active_membership),
    user: User=Depends(current_user),db: Session=Depends(get_db)):
    require_permission(membership,"manage")
    _crm_branch_check(db,membership,payload.branch_id)
    row=CRMCampaign(organization_id=membership.organization_id,branch_id=payload.branch_id,
        campaign_number=payload.campaign_number.strip().upper(),name=payload.name,
        channel=payload.channel,purpose="marketing",message=payload.message,
        status="draft",created_by=user.id)
    db.add(row)
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Campaign number already exists in this organization")
    db.refresh(row)
    audit(db,user.id,membership.organization_id,"crm.campaign.created","crm_campaign",row.id)
    return {"id":row.id,"campaign_number":row.campaign_number,"status":row.status,
            "channel":row.channel,"branch_id":row.branch_id}


@router.get("/crm/campaigns")
def list_crm_campaigns(membership=Depends(active_membership),db: Session=Depends(get_db),
                       limit: int=Query(default=100,ge=1,le=500)):
    require_permission(membership,"read")
    q=db.query(CRMCampaign).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:return []
        q=q.filter(CRMCampaign.branch_id.in_(allowed))
    rows=q.order_by(CRMCampaign.id.desc()).limit(limit).all()
    result=[]
    for row in rows:
        count=db.query(func.count(CRMCampaignRecipient.id)).filter_by(
            organization_id=membership.organization_id,campaign_id=row.id).scalar()
        result.append({"id":row.id,"campaign_number":row.campaign_number,"name":row.name,
            "channel":row.channel,"status":row.status,"recipient_count":count,
            "prepared_at":row.prepared_at.isoformat() if row.prepared_at else None,
            "branch_id":row.branch_id})
    return result


@router.get("/crm/campaigns/{campaign_id}")
def get_crm_campaign(campaign_id: int,membership=Depends(active_membership),
                     db: Session=Depends(get_db)):
    require_permission(membership,"read")
    row=db.query(CRMCampaign).filter_by(
        id=campaign_id,organization_id=membership.organization_id).first()
    if not row or not can_access_branch(membership,row.branch_id):
        raise HTTPException(404,"Campaign not found")
    recipients=db.query(CRMCampaignRecipient).filter_by(
        organization_id=membership.organization_id,campaign_id=row.id
    ).order_by(CRMCampaignRecipient.id).all()
    return {"id":row.id,"campaign_number":row.campaign_number,"name":row.name,
        "channel":row.channel,"message":row.message,"status":row.status,
        "recipient_count":len(recipients),
        "recipients":[{"contact_id":x.contact_id,"channel":x.channel,
            "address_snapshot":x.address_snapshot,"consent_id":x.consent_id,
            "status":x.status} for x in recipients]}


@router.post("/crm/campaigns/{campaign_id}/prepare")
def prepare_crm_campaign(campaign_id: int,segment_id: int | None = Query(default=None,ge=1),membership=Depends(active_membership),
    user: User=Depends(current_user),db: Session=Depends(get_db)):
    require_permission(membership,"manage")
    campaign=db.query(CRMCampaign).filter_by(
        id=campaign_id,organization_id=membership.organization_id
    ).with_for_update().first()
    if not campaign or not can_access_branch(membership,campaign.branch_id):
        raise HTTPException(404,"Campaign not found")
    existing=db.query(CRMCampaignRecipient).filter_by(
        organization_id=membership.organization_id,campaign_id=campaign.id).count()
    if campaign.status=="ready":
        return {"id":campaign.id,"status":campaign.status,"recipient_count":existing,
                "already_prepared":True}
    if campaign.status!="draft":
        raise HTTPException(409,"Only draft campaigns can be prepared")
    latest_consent=db.query(
        func.max(CRMContactConsent.id).label("latest_id")
    ).filter(
        CRMContactConsent.organization_id==membership.organization_id,
        CRMContactConsent.channel==campaign.channel,
        CRMContactConsent.purpose==campaign.purpose,
    ).group_by(CRMContactConsent.contact_id).subquery()
    q=db.query(CRMContact,CRMContactConsent).join(
        CRMContactConsent,CRMContactConsent.contact_id==CRMContact.id
    ).join(latest_consent,latest_consent.c.latest_id==CRMContactConsent.id).filter(
        CRMContact.organization_id==membership.organization_id,
        CRMContactConsent.organization_id==membership.organization_id,
        CRMContactConsent.decision=="granted",
        or_(CRMContactConsent.expires_at.is_(None),
            CRMContactConsent.expires_at>datetime.now(timezone.utc)),
    )
    if segment_id is not None:
        from app.core.models import CRMAudienceSegment
        from app.api.crm_automation import compile_rules
        segment=db.query(CRMAudienceSegment).filter_by(id=segment_id,organization_id=membership.organization_id,is_active=True).first()
        if not segment: raise HTTPException(404,"Audience segment not found")
        rules=segment.rules or {}
        for condition in compile_rules({"all":rules.get("all",[])}): q=q.filter(condition)
        any_conditions=compile_rules({"any":rules.get("any",[])})
        if any_conditions: q=q.filter(or_(*any_conditions))
    if campaign.branch_id:
        q=q.filter(CRMContact.branch_id==campaign.branch_id)
    else:
        allowed=branch_scope_ids(membership)
        if allowed is not None:
            if not allowed:q=q.filter(CRMContact.id==-1)
            else:q=q.filter(CRMContact.branch_id.in_(allowed))
    contacts=q.order_by(CRMContact.id).limit(5000).all()
    prepared=0
    for contact,consent in contacts:
        address=contact.email if campaign.channel=="email" else contact.phone
        if not address: continue
        db.add(CRMCampaignRecipient(
            organization_id=membership.organization_id,campaign_id=campaign.id,
            contact_id=contact.id,consent_id=consent.id,channel=campaign.channel,
            address_snapshot=address,status="prepared"))
        prepared+=1
    campaign.status="ready";campaign.prepared_at=datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,"Campaign recipient preparation conflicted; reload and retry")
    audit(db,user.id,membership.organization_id,"crm.campaign.prepared",
          "crm_campaign",campaign.id,f"recipients:{prepared}")
    return {"id":campaign.id,"status":campaign.status,"recipient_count":prepared,
            "delivery_started":False,"message":"Recipients prepared; no messages were sent"}


@router.get("/crm/forecast")
def crm_pipeline_forecast(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    q=db.query(CRMLead).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:return {"currency":None,"pipeline_total":"0","weighted_forecast":"0","stages":[]}
        q=q.filter(CRMLead.branch_id.in_(allowed))
    rows=q.all()
    probabilities={"new":Decimal("0.10"),"qualified":Decimal("0.25"),
        "proposal":Decimal("0.50"),"negotiation":Decimal("0.75"),"won":Decimal("1.00"),"lost":Decimal("0")}
    currencies={}
    for row in rows:
        bucket=currencies.setdefault(row.currency,{"pipeline":Decimal("0"),"weighted":Decimal("0"),"stages":{}})
        value=Decimal(row.estimated_value);weighted=value*probabilities[row.stage]
        bucket["pipeline"]+=value;bucket["weighted"]+=weighted
        stage=bucket["stages"].setdefault(row.stage,{"count":0,"value":Decimal("0"),"weighted":Decimal("0")})
        stage["count"]+=1;stage["value"]+=value;stage["weighted"]+=weighted
    return {"forecasts":[{"currency":currency,"pipeline_total":str(data["pipeline"]),
        "weighted_forecast":str(data["weighted"]),
        "stages":[{"stage":stage,"count":v["count"],"value":str(v["value"]),
            "weighted_value":str(v["weighted"])} for stage,v in sorted(data["stages"].items())]}
        for currency,data in sorted(currencies.items())],
        "method":"Fixed stage probability assumptions; not a statistical prediction"}


@router.post("/school/attendance", status_code=200)
def record_school_attendance(payload: SchoolAttendanceIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    """Create or correct a daily register; one entry per learner/date."""
    require_permission(membership, "create")
    cls=db.query(SchoolClass).filter_by(
        id=payload.class_id, organization_id=membership.organization_id, is_active=True).first()
    if not cls or not can_access_branch(membership, cls.branch_id):
        raise HTTPException(404, "Class not found")
    learner_ids=[entry.learner_id for entry in payload.entries]
    learners=db.query(SchoolLearner).filter(
        SchoolLearner.organization_id==membership.organization_id,
        SchoolLearner.class_id==cls.id, SchoolLearner.status=="active",
        SchoolLearner.id.in_(learner_ids)).all()
    if {x.id for x in learners} != set(learner_ids):
        raise HTTPException(422, "Every learner must be active and enrolled in this class")
    stamp=datetime.combine(payload.attendance_date,time.min,tzinfo=timezone.utc)
    saved=[]
    try:
        for entry in payload.entries:
            row=db.query(SchoolAttendance).filter_by(
                organization_id=membership.organization_id,
                attendance_date=stamp, learner_id=entry.learner_id).with_for_update().first()
            if row:
                if row.class_id != cls.id:
                    raise HTTPException(409, "Learner already has an attendance entry for this date")
                row.status=entry.status
                row.note=entry.note
                row.recorded_by=user.id
            else:
                row=SchoolAttendance(organization_id=membership.organization_id,
                    branch_id=cls.branch_id,class_id=cls.id,learner_id=entry.learner_id,
                    attendance_date=stamp,status=entry.status,note=entry.note,recorded_by=user.id)
                db.add(row)
            saved.append(row)
        db.flush()
        db.add(AuditEvent(actor_user_id=user.id,organization_id=membership.organization_id,
            action="school.attendance.recorded",resource_type="school_attendance",
            resource_id=str(cls.id),detail=f"{payload.attendance_date.isoformat()}:{len(saved)}"))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"class_id":cls.id,"attendance_date":payload.attendance_date.isoformat(),
        "count":len(saved),"entries":[{"learner_id":x.learner_id,"status":x.status,"note":x.note} for x in saved]}


@router.get("/school/attendance")
def list_school_attendance(class_id:int, attendance_date:date,
    membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    cls=db.query(SchoolClass).filter_by(
        id=class_id,organization_id=membership.organization_id,is_active=True).first()
    if not cls or not can_access_branch(membership,cls.branch_id):
        raise HTTPException(404,"Class not found")
    stamp=datetime.combine(attendance_date,time.min,tzinfo=timezone.utc)
    rows=db.query(SchoolAttendance,SchoolLearner).join(
        SchoolLearner,SchoolLearner.id==SchoolAttendance.learner_id).filter(
        SchoolAttendance.organization_id==membership.organization_id,
        SchoolAttendance.class_id==cls.id,SchoolAttendance.attendance_date==stamp).order_by(
        SchoolLearner.admission_number).all()
    return {"class_id":cls.id,"attendance_date":attendance_date.isoformat(),
        "entries":[{"learner_id":a.learner_id,"admission_number":l.admission_number,
        "learner":f"{l.first_name} {l.last_name}","status":a.status,"note":a.note}
        for a,l in rows]}


@router.post("/school/learners/{learner_id}/placements", status_code=201)
def change_school_learner_placement(learner_id: int, payload: SchoolLearnerPlacementIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    """Promote or transfer an active learner while retaining the previous placement."""
    require_permission(membership, "manage")
    learner = db.query(SchoolLearner).filter_by(
        id=learner_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not learner or learner.status != "active" or not can_access_branch(membership, learner.branch_id):
        raise HTTPException(404, "Active learner not found")
    if not learner.class_id:
        raise HTTPException(409, "Learner must have a current class before a placement change")
    source = db.query(SchoolClass).filter_by(
        id=learner.class_id, organization_id=membership.organization_id
    ).first()
    target = db.query(SchoolClass).filter_by(
        id=payload.target_class_id, organization_id=membership.organization_id, is_active=True
    ).first()
    if not source or not target:
        raise HTTPException(404, "Source or target class not found")
    if not can_access_branch(membership, source.branch_id) or not can_access_branch(membership, target.branch_id):
        raise HTTPException(403, "Access to both source and target branches is required")
    if source.id == target.id:
        raise HTTPException(409, "Learner is already enrolled in the target class")
    if target.academic_year < source.academic_year:
        raise HTTPException(422, "A learner cannot be moved to an earlier academic year")
    if payload.change_type == "promotion" and target.academic_year <= source.academic_year:
        raise HTTPException(422, "A promotion must move the learner to a later academic year")
    if payload.effective_date < source.created_at.date():
        raise HTTPException(422, "Effective date cannot precede the source class creation date")
    history = SchoolEnrollmentHistory(
        organization_id=membership.organization_id, learner_id=learner.id,
        from_class_id=source.id, to_class_id=target.id,
        effective_date=datetime.combine(payload.effective_date, time.min, tzinfo=timezone.utc),
        change_type=payload.change_type, reason=payload.reason, changed_by=user.id,
    )
    learner.class_id = target.id
    learner.branch_id = target.branch_id
    db.add(history)
    db.add(AuditEvent(actor_user_id=user.id, organization_id=membership.organization_id,
        action=f"school.learner.{payload.change_type}", resource_type="school_learner",
        resource_id=str(learner.id),
        detail=f"from_class:{source.id};to_class:{target.id};effective:{payload.effective_date.isoformat()}"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Learner placement changed concurrently; reload and retry")
    db.refresh(history)
    return {"learner_id": learner.id, "from_class_id": source.id, "to_class_id": target.id,
        "change_type": history.change_type, "effective_date": payload.effective_date.isoformat(),
        "history_id": history.id}


@router.get("/school/learners/{learner_id}/placements")
def list_school_learner_placements(learner_id: int,
    membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    learner = db.query(SchoolLearner).filter_by(
        id=learner_id, organization_id=membership.organization_id
    ).first()
    if not learner or not can_access_branch(membership, learner.branch_id):
        raise HTTPException(404, "Learner not found")
    rows = db.query(SchoolEnrollmentHistory).filter_by(
        organization_id=membership.organization_id, learner_id=learner.id
    ).order_by(SchoolEnrollmentHistory.effective_date, SchoolEnrollmentHistory.id).all()
    results = []
    for row in rows:
        source = db.query(SchoolClass).filter_by(
            id=row.from_class_id, organization_id=membership.organization_id).first()
        target = db.query(SchoolClass).filter_by(
            id=row.to_class_id, organization_id=membership.organization_id).first()
        if not source or not target or not can_access_branch(membership, source.branch_id) or not can_access_branch(membership, target.branch_id):
            raise HTTPException(404, "Placement history not found")
        results.append({"id": row.id, "from_class_id": source.id, "from_class": source.name,
            "from_academic_year": source.academic_year, "to_class_id": target.id,
            "to_class": target.name, "to_academic_year": target.academic_year,
            "change_type": row.change_type, "effective_date": row.effective_date.date().isoformat(),
            "reason": row.reason, "changed_by": row.changed_by})
    return {"learner_id": learner.id, "current_class_id": learner.class_id, "placements": results}

