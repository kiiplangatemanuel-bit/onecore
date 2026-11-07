import json, re, uuid, hashlib
from decimal import Decimal
from sqlalchemy import func, and_, or_
from sqlalchemy.exc import IntegrityError
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import User, Organization, Membership, Branch, Record, AuditEvent, InventoryProduct, InventoryStockMovement, AccountingAccount, AccountingJournal, AccountingJournalLine, AccountingInvoice, AccountingInvoiceLine, AccountingInvoicePayment, AccountingFiscalPeriod, AccountingBudget, AccountingBudgetLine, AccountingFixedAsset, AccountingDepreciationEntry, AccountingBankStatement, AccountingBankStatementLine, AccountingInvoiceApproval, AccountingCreditNote, AccountingCreditNoteLine, CRMContact, CRMLead, CRMActivity, CRMQuote, CRMQuoteLine, CRMSalesOrder, CRMSalesOrderLine, CRMContactConsent, CRMCampaign, CRMCampaignRecipient, ProcurementSupplier, ProcurementPurchaseOrder, ProcurementPurchaseOrderLine, ProcurementRequisition, ProcurementRequisitionLine, ProcurementGoodsReceipt, ProcurementGoodsReceiptLine, ProcurementApprovalRule, ProcurementApprovalAction, ProcurementRFQ, ProcurementRFQLine, ProcurementRFQInvitation, ProcurementRFQQuote, ProcurementRFQQuoteLine, ProcurementSupplierInvoice, ProcurementSupplierInvoiceLine, ProcurementSupplierReturn, ProcurementSupplierReturnLine, POSShift, POSSale, POSSaleLine, POSPayment, POSReturn, POSReturnLine, POSRefund, HREmployee, HRLeaveRequest, HRAttendance, HRPayrollProfile, HRPayrollRun, HRPayrollLine, HRPayrollItem, HealthcarePatient, HealthcareAppointment, HealthcareEncounter, PharmacyMedicine, PharmacyBatch, LaboratoryTest, LaboratoryOrder, LaboratoryOrderLine, LaboratorySample, SaccoMember, SaccoAccount, SaccoTransaction, SaccoLoanProduct, SaccoLoanApplication, SaccoLoan, SaccoLoanSchedule, SaccoLoanRepayment, SchoolClass, SchoolLearner, SchoolSubject, SchoolAssessment, SchoolMark, SchoolGradeBand, SchoolAttendance, SchoolEnrollmentHistory
from app.core.schemas import OrganizationIn, RecordIn, BranchIn, InventoryProductIn, InventoryMovementIn, AccountingAccountIn, AccountingJournalIn, AccountingInvoiceIn, AccountingInvoicePaymentIn, AccountingFiscalPeriodIn, AccountingBudgetIn, AccountingFixedAssetIn, AccountingDepreciationIn, AccountingBankStatementIn, AccountingBankMatchIn, AccountingInvoiceApprovalDecisionIn, AccountingCreditNoteIn, CRMContactIn, CRMLeadIn, CRMLeadStageIn, CRMActivityIn, CRMQuoteIn, CRMQuoteConvertIn, CRMContactConsentIn, CRMCampaignIn, ProcurementSupplierIn, PurchaseOrderIn, PurchaseOrderReceiptIn, ProcurementRequisitionIn, ProcurementRequisitionReviewIn, GoodsReceiptIn, GoodsReceiptInspectionIn, RequisitionConvertIn, ProcurementApprovalRuleIn, ProcurementRFQIn, ProcurementRFQQuoteIn, SupplierInvoiceIn, SupplierReturnIn, POSShiftOpenIn, POSShiftCloseIn, POSSaleSyncIn, POSReturnIn, SchoolClassIn, SchoolLearnerIn, SchoolSubjectIn, SchoolAssessmentIn, SchoolMarksIn, SchoolGradeBandIn, SchoolAttendanceIn, SchoolLearnerPlacementIn, HREmployeeIn, HRLeaveRequestIn, HRLeaveDecisionIn, HRPayrollProfileIn, HRPayrollRunIn, HRPayrollItemIn, HRPayrollApproveIn, HealthcarePatientIn, HealthcareAppointmentIn, HealthcareAppointmentStatusIn, HealthcareEncounterIn, HealthcareEncounterSignIn, PharmacyMedicineIn, PharmacyBatchIn, PharmacyBatchQuarantineIn, LaboratoryTestIn, LaboratoryOrderIn, LaboratorySampleIn, LaboratoryResultIn, LaboratoryValidateIn, SaccoMemberIn, SaccoKYCDecisionIn, SaccoAccountIn, SaccoTransactionIn, SaccoLoanProductIn, SaccoLoanApplicationIn, SaccoLoanDecisionIn, SaccoLoanDisbursementIn, SaccoLoanRepaymentIn
from app.core.security import current_user, verify_password, create_access_token, require_platform_admin
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, branch_scope_ids, can_access_branch
from app.integrations.registry import public_provider_status
from app.services.inventory import validate_stock_delta, resulting_balance
from app.services.accounting import validate_journal_lines
from app.services.crm import validate_stage_transition
from app.services.hr import business_days, worked_minutes, payroll_money, payroll_item_hash, payroll_totals
from app.services.hr import business_days, worked_minutes, payroll_money, payroll_item_hash, payroll_totals
from app.services.healthcare import validate_appointment_transition
from app.services.pharmacy_lab import pharmacy_batch_hash, laboratory_order_hash
from app.services.sacco import build_repayment_schedule, add_months, allocate_repayment, money as sacco_money
from app.services.school_reports import build_learner_report_rows
from app.services.pos import money, validate_payment_total, canonical_request_hash, canonical_return_hash, validate_return_refund_total
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
    returned = db.query(POSReturnLine.sale_line_id, func.coalesce(func.sum(POSReturnLine.quantity), 0)).join(
        POSReturn, POSReturn.id == POSReturnLine.return_id
    ).filter(POSReturn.organization_id == membership.organization_id,
             POSReturn.sale_id == sale.id).group_by(POSReturnLine.sale_line_id).all()
    returned_map = {line_id: quantity for line_id, quantity in returned}
    payments = db.query(POSPayment).filter_by(
        organization_id=membership.organization_id, sale_id=sale.id
    ).order_by(POSPayment.id).all()
    return {
        "id": sale.id, "branch_id": sale.branch_id, "shift_id": sale.shift_id,
        "currency": sale.currency, "status": sale.status,
        "total_amount": str(sale.total_amount), "created_at": sale.created_at.isoformat(),
        "lines": [{
            "id": line.id, "product_id": line.product_id, "sku": sku, "name": name,
            "quantity": str(line.quantity), "returned_quantity": str(returned_map.get(line.id, 0)),
            "returnable_quantity": str(Decimal(str(line.quantity)) - Decimal(str(returned_map.get(line.id, 0)))),
            "unit_price": str(line.unit_price), "line_total": str(line.line_total),
        } for line, name, sku in lines],
        "payments": [{"method": p.method, "amount": str(p.amount), "status": p.status,
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
    already_returned = db.query(POSReturnLine.sale_line_id,
        func.coalesce(func.sum(POSReturnLine.quantity), 0)).join(
        POSReturn, POSReturn.id == POSReturnLine.return_id
    ).filter(POSReturn.organization_id == membership.organization_id,
             POSReturn.sale_id == sale.id,
             POSReturnLine.sale_line_id.in_(line_ids)).group_by(POSReturnLine.sale_line_id).all()
    returned_map = {line_id: Decimal(str(quantity)) for line_id, quantity in already_returned}
    total = Decimal("0.00")
    prepared = []
    for item in payload.lines:
        original = line_map[item.sale_line_id]
        remaining = Decimal(str(original.quantity)) - returned_map.get(original.id, Decimal("0"))
        if item.quantity > remaining:
            raise HTTPException(409, f"Return quantity exceeds remaining sold quantity for line {original.id}")
        amount = money(Decimal(str(original.unit_price)) * item.quantity)
        total += amount
        prepared.append((original, item.quantity, amount))
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
    for index, (original, quantity, amount) in enumerate(prepared):
        db.add(POSReturnLine(organization_id=membership.organization_id, return_id=result.id,
            sale_line_id=original.id, product_id=original.product_id, quantity=quantity,
            unit_price=original.unit_price, line_total=amount))
        db.add(InventoryStockMovement(organization_id=membership.organization_id,
            product_id=original.product_id, branch_id=sale.branch_id, quantity_delta=quantity,
            movement_type="receipt", reference=payload.client_return_id,
            idempotency_key=f"pos-return:{return_key}:{index}", created_by=user.id))
    for item in payload.refunds:
        db.add(POSRefund(organization_id=membership.organization_id, return_id=result.id,
            method=item.method, amount=money(item.amount), provider_reference=item.provider_reference,
            status="recorded"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(POSReturn).filter_by(
            organization_id=membership.organization_id, client_return_id=payload.client_return_id
        ).first()
        if existing and existing.request_hash == request_hash and existing.sale_id == sale_id:
            return {"id": existing.id, "sale_id": existing.sale_id, "status": "already_recorded",
                    "refund_total": str(existing.refund_total)}
        raise HTTPException(409, "Return conflicts with another return or stock movement")
    db.refresh(result)
    audit(db, user.id, membership.organization_id, "pos.sale.returned",
          "pos_return", result.id, f"sale:{sale.id};refund:{total};reason:{payload.reason.strip()}")
    return {"id": result.id, "sale_id": sale.id, "status": "recorded",
            "refund_total": str(result.refund_total), "currency": sale.currency,
            "stock_reintegrated": True, "refunds_executed": False}


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
    outstanding=Decimal(invoice.total)-Decimal(invoice.amount_paid)
    if total>outstanding:
        raise HTTPException(409,"Credit exceeds the outstanding invoice balance; customer refunds and supplier credit balances are not yet supported")
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
    counts = {
        "draft_invoices": draft_invoices,
        "pending_invoice_approvals": pending_approvals,
        "draft_credit_notes": draft_credit_notes,
        "draft_journals": draft_journals,
        "unreconciled_bank_statements": unreconciled_bank_statements,
        "unbalanced_posted_journals": unbalanced_posted_journals,
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
def prepare_crm_campaign(campaign_id: int,membership=Depends(active_membership),
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



@router.post("/hr/employees",status_code=201)
def create_hr_employee(payload:HREmployeeIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    _crm_branch_check(db,membership,payload.branch_id)
    if payload.user_id and not db.query(Membership).filter_by(
        user_id=payload.user_id,organization_id=membership.organization_id,is_active=True
    ).first():
        raise HTTPException(404,"Linked user is not an active member of this organization")
    if db.query(HREmployee).filter_by(
        organization_id=membership.organization_id,
        employee_number=payload.employee_number.strip().upper()).first():
        raise HTTPException(409,"Employee number already exists in this organization")
    row=HREmployee(organization_id=membership.organization_id,branch_id=payload.branch_id,
        user_id=payload.user_id,employee_number=payload.employee_number.strip().upper(),
        first_name=payload.first_name,last_name=payload.last_name,
        email=str(payload.email).lower() if payload.email else None,
        phone=payload.phone.strip() if payload.phone else None,
        department=payload.department.strip(),job_title=payload.job_title.strip(),
        employment_type=payload.employment_type,status="active",
        start_date=payload.start_date,created_by=user.id)
    db.add(row)
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Employee number conflicts with an existing employee")
    db.refresh(row)
    audit(db,user.id,membership.organization_id,"hr.employee.created","hr_employee",row.id)
    return {"id":row.id,"employee_number":row.employee_number,
        "name":f"{row.first_name} {row.last_name}","branch_id":row.branch_id,"status":row.status}


@router.get("/hr/employees")
def list_hr_employees(membership=Depends(active_membership),db:Session=Depends(get_db),
                      limit:int=Query(default=100,ge=1,le=500)):
    require_permission(membership,"read")
    q=db.query(HREmployee).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:return []
        q=q.filter(HREmployee.branch_id.in_(allowed))
    rows=q.order_by(HREmployee.id.desc()).limit(limit).all()
    return [{"id":x.id,"employee_number":x.employee_number,
        "name":f"{x.first_name} {x.last_name}","email":x.email,"phone":x.phone,
        "department":x.department,"job_title":x.job_title,
        "employment_type":x.employment_type,"status":x.status,
        "start_date":x.start_date.isoformat(),"branch_id":x.branch_id} for x in rows]


@router.post("/hr/leave-requests",status_code=201)
def create_hr_leave_request(payload:HRLeaveRequestIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    employee=db.query(HREmployee).filter_by(
        id=payload.employee_id,organization_id=membership.organization_id,status="active"
    ).first()
    if not employee or not can_access_branch(membership,employee.branch_id):
        raise HTTPException(404,"Active employee not found")
    if employee.user_id==user.id:
        require_permission(membership,"create")
    else:
        require_permission(membership,"manage")
    days=business_days(payload.start_date,payload.end_date)
    if days<=0:
        raise HTTPException(422,"Leave period must include at least one working day")
    overlap=db.query(HRLeaveRequest).filter(
        HRLeaveRequest.organization_id==membership.organization_id,
        HRLeaveRequest.employee_id==employee.id,
        HRLeaveRequest.status.in_(["pending","approved"]),
        HRLeaveRequest.start_date<=payload.end_date,
        HRLeaveRequest.end_date>=payload.start_date,
    ).first()
    if overlap:
        raise HTTPException(409,"Leave dates overlap an existing pending or approved request")
    row=HRLeaveRequest(organization_id=membership.organization_id,
        employee_id=employee.id,branch_id=employee.branch_id,leave_type=payload.leave_type,
        start_date=payload.start_date,end_date=payload.end_date,
        working_days=Decimal(days),reason=payload.reason.strip(),status="pending",
        requested_by=user.id)
    db.add(row);db.commit();db.refresh(row)
    audit(db,user.id,membership.organization_id,"hr.leave.requested",
          "hr_leave_request",row.id,f"employee:{employee.id};days:{days}")
    return {"id":row.id,"employee_id":employee.id,"start_date":row.start_date.isoformat(),
        "end_date":row.end_date.isoformat(),"working_days":str(row.working_days),"status":row.status}


@router.get("/hr/my-leave-requests")
def list_my_hr_leave_requests(membership=Depends(active_membership),
                              user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    employee=db.query(HREmployee).filter_by(
        organization_id=membership.organization_id,user_id=user.id,status="active"
    ).first()
    if not employee:return []
    rows=db.query(HRLeaveRequest).filter_by(
        organization_id=membership.organization_id,employee_id=employee.id
    ).order_by(HRLeaveRequest.id.desc()).limit(200).all()
    return [{"id":x.id,"leave_type":x.leave_type,"start_date":x.start_date.isoformat(),
        "end_date":x.end_date.isoformat(),"working_days":str(x.working_days),
        "reason":x.reason,"status":x.status,"decision_note":x.decision_note} for x in rows]


@router.get("/hr/leave-requests")
def list_hr_leave_requests(membership=Depends(active_membership),db:Session=Depends(get_db),
                           limit:int=Query(default=100,ge=1,le=500)):
    require_permission(membership,"manage")
    q=db.query(HRLeaveRequest).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:return []
        q=q.filter(HRLeaveRequest.branch_id.in_(allowed))
    rows=q.order_by(HRLeaveRequest.id.desc()).limit(limit).all()
    result=[]
    for x in rows:
        employee=db.query(HREmployee).filter_by(
            id=x.employee_id,organization_id=membership.organization_id).first()
        result.append({"id":x.id,"employee_id":x.employee_id,
            "employee_name":f"{employee.first_name} {employee.last_name}" if employee else "Unknown",
            "employee_number":employee.employee_number if employee else "",
            "leave_type":x.leave_type,"start_date":x.start_date.isoformat(),
            "end_date":x.end_date.isoformat(),"working_days":str(x.working_days),
            "reason":x.reason,"status":x.status,"decision_note":x.decision_note})
    return result


@router.post("/hr/leave-requests/{request_id}/decision")
def decide_hr_leave_request(request_id:int,payload:HRLeaveDecisionIn,
    membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(HRLeaveRequest).filter_by(
        id=request_id,organization_id=membership.organization_id
    ).with_for_update().first()
    if not row or not can_access_branch(membership,row.branch_id):
        raise HTTPException(404,"Leave request not found")
    employee=db.query(HREmployee).filter_by(
        id=row.employee_id,organization_id=membership.organization_id).first()
    if employee and employee.user_id==user.id:
        raise HTTPException(403,"Employees cannot approve or reject their own leave")
    if row.status!="pending":
        raise HTTPException(409,"Only pending leave requests can be decided")
    row.status=payload.decision;row.decided_by=user.id
    row.decided_at=datetime.now(timezone.utc);row.decision_note=payload.note.strip()
    db.commit()
    audit(db,user.id,membership.organization_id,f"hr.leave.{payload.decision}",
          "hr_leave_request",row.id)
    return {"id":row.id,"status":row.status,"decided_at":row.decided_at.isoformat()}



@router.post("/hr/attendance/clock-in", status_code=201)
def hr_attendance_clock_in(membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    employee=db.query(HREmployee).filter_by(
        organization_id=membership.organization_id,user_id=user.id,status="active"
    ).first()
    if not employee or not can_access_branch(membership,employee.branch_id):
        raise HTTPException(404,"An active employee profile linked to your account was not found")
    today=datetime.now(timezone.utc).date()
    existing=db.query(HRAttendance).filter_by(
        organization_id=membership.organization_id,employee_id=employee.id,
        attendance_date=today
    ).with_for_update().first()
    if existing:
        raise HTTPException(409,"Attendance has already been started for today")
    row=HRAttendance(organization_id=membership.organization_id,
        employee_id=employee.id,branch_id=employee.branch_id,attendance_date=today,
        clock_in_at=datetime.now(timezone.utc))
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,"Attendance was already started for today")
    db.refresh(row)
    audit(db,user.id,membership.organization_id,"hr.attendance.clocked_in",
          "hr_attendance",row.id)
    return {"id":row.id,"attendance_date":row.attendance_date.isoformat(),
        "clock_in_at":row.clock_in_at.isoformat(),"status":"clocked_in"}


@router.post("/hr/attendance/clock-out")
def hr_attendance_clock_out(membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    employee=db.query(HREmployee).filter_by(
        organization_id=membership.organization_id,user_id=user.id,status="active"
    ).first()
    if not employee or not can_access_branch(membership,employee.branch_id):
        raise HTTPException(404,"An active employee profile linked to your account was not found")
    today=datetime.now(timezone.utc).date()
    row=db.query(HRAttendance).filter_by(
        organization_id=membership.organization_id,employee_id=employee.id,
        attendance_date=today
    ).with_for_update().first()
    if not row:
        raise HTTPException(409,"Clock in before clocking out")
    if row.clock_out_at:
        raise HTTPException(409,"Attendance has already been clocked out")
    now_utc=datetime.now(timezone.utc)
    started=row.clock_in_at
    if started.tzinfo is None:
        started=started.replace(tzinfo=timezone.utc)
    try:
        elapsed=worked_minutes(started,now_utc)
    except ValueError:
        raise HTTPException(409,"Clock-in timestamp is invalid")
    row.clock_out_at=now_utc
    row.worked_minutes=elapsed
    db.commit()
    audit(db,user.id,membership.organization_id,"hr.attendance.clocked_out",
          "hr_attendance",row.id,f"worked_minutes:{elapsed}")
    return {"id":row.id,"attendance_date":row.attendance_date.isoformat(),
        "clock_in_at":started.isoformat(),"clock_out_at":now_utc.isoformat(),
        "worked_minutes":elapsed,"status":"completed"}


@router.get("/hr/my-attendance")
def hr_my_attendance(membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db),
    limit:int=Query(default=31,ge=1,le=180)):
    require_permission(membership,"read")
    employee=db.query(HREmployee).filter_by(
        organization_id=membership.organization_id,user_id=user.id,status="active"
    ).first()
    if not employee:
        return []
    rows=db.query(HRAttendance).filter_by(
        organization_id=membership.organization_id,employee_id=employee.id
    ).order_by(HRAttendance.attendance_date.desc()).limit(limit).all()
    return [{"id":x.id,"attendance_date":x.attendance_date.isoformat(),
        "clock_in_at":x.clock_in_at.isoformat(),
        "clock_out_at":x.clock_out_at.isoformat() if x.clock_out_at else None,
        "worked_minutes":x.worked_minutes,"status":"completed" if x.clock_out_at else "clocked_in"}
        for x in rows]


@router.get("/hr/attendance")
def hr_attendance_report(membership=Depends(active_membership),
    db:Session=Depends(get_db),limit:int=Query(default=100,ge=1,le=500)):
    require_permission(membership,"manage")
    q=db.query(HRAttendance,HREmployee).join(
        HREmployee,HREmployee.id==HRAttendance.employee_id
    ).filter(HRAttendance.organization_id==membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:return []
        q=q.filter(HRAttendance.branch_id.in_(allowed))
    rows=q.order_by(HRAttendance.attendance_date.desc(),HRAttendance.id.desc()).limit(limit).all()
    return [{"id":x.id,"employee_id":employee.id,
        "employee_number":employee.employee_number,
        "employee_name":f"{employee.first_name} {employee.last_name}",
        "branch_id":x.branch_id,"attendance_date":x.attendance_date.isoformat(),
        "clock_in_at":x.clock_in_at.isoformat(),
        "clock_out_at":x.clock_out_at.isoformat() if x.clock_out_at else None,
        "worked_minutes":x.worked_minutes,
        "status":"completed" if x.clock_out_at else "clocked_in"}
        for x,employee in rows]




# Payroll uses effective-dated base pay and explicit one-off earning/deduction items.
# Statutory calculations and payment execution are deliberately not inferred.
def _hr_payroll_run_lines(db, membership, run):
    lines = db.query(HRPayrollLine).filter_by(
        organization_id=membership.organization_id, run_id=run.id
    ).order_by(HRPayrollLine.employee_number, HRPayrollLine.employee_id).all()
    if not lines:
        raise HTTPException(404, "Payroll run not found")
    if any(not can_access_branch(membership, line.branch_id) for line in lines):
        raise HTTPException(404, "Payroll run not found")
    return lines


def _hr_payroll_run_out(run):
    return {
        "id": run.id, "run_number": run.run_number,
        "period_start": run.period_start.isoformat(),
        "period_end": run.period_end.isoformat(),
        "pay_date": run.pay_date.isoformat(), "currency": run.currency,
        "status": run.status, "gross_total": str(run.gross_total),
        "deductions_total": str(run.deductions_total),
        "net_total": str(run.net_total), "created_by": run.created_by,
        "approved_by": run.approved_by,
        "approved_at": run.approved_at.isoformat() if run.approved_at else None,
    }


@router.post("/hr/payroll/profiles", status_code=201)
def create_hr_payroll_profile(payload: HRPayrollProfileIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    employee = db.query(HREmployee).filter_by(
        id=payload.employee_id, organization_id=membership.organization_id, status="active"
    ).first()
    if not employee or not can_access_branch(membership, employee.branch_id):
        raise HTTPException(404, "Active employee not found")
    if payload.effective_from < employee.start_date:
        raise HTTPException(422, "Payroll profile cannot start before the employee start date")
    if employee.end_date and (payload.effective_to is None or payload.effective_to > employee.end_date):
        raise HTTPException(422, "Payroll profile must end no later than the employee end date")
    q = db.query(HRPayrollProfile).filter(
        HRPayrollProfile.organization_id == membership.organization_id,
        HRPayrollProfile.employee_id == employee.id,
        HRPayrollProfile.effective_from <= (payload.effective_to or date.max),
        or_(HRPayrollProfile.effective_to.is_(None),
            HRPayrollProfile.effective_to >= payload.effective_from),
    )
    if q.first():
        raise HTTPException(409, "Payroll profile effective dates overlap an existing profile")
    row = HRPayrollProfile(
        organization_id=membership.organization_id, employee_id=employee.id,
        branch_id=employee.branch_id, currency=payload.currency,
        base_period_pay=payroll_money(payload.base_period_pay),
        effective_from=payload.effective_from, effective_to=payload.effective_to,
        created_by=user.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Payroll profile conflicts with an existing effective date")
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "hr.payroll.profile.created",
          "hr_payroll_profile", row.id, f"employee:{employee.id};currency:{row.currency}")
    return {"id": row.id, "employee_id": employee.id, "currency": row.currency,
            "base_period_pay": str(row.base_period_pay),
            "effective_from": row.effective_from.isoformat(),
            "effective_to": row.effective_to.isoformat() if row.effective_to else None}


@router.get("/hr/payroll/profiles")
def list_hr_payroll_profiles(membership=Depends(active_membership), db: Session=Depends(get_db),
    limit: int=Query(default=200, ge=1, le=1000)):
    require_permission(membership, "manage")
    q = db.query(HRPayrollProfile, HREmployee).join(
        HREmployee, HREmployee.id == HRPayrollProfile.employee_id
    ).filter(HRPayrollProfile.organization_id == membership.organization_id)
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            return []
        q = q.filter(HRPayrollProfile.branch_id.in_(allowed))
    rows = q.order_by(HRPayrollProfile.effective_from.desc(),
                      HRPayrollProfile.id.desc()).limit(limit).all()
    return [{
        "id": profile.id, "employee_id": employee.id,
        "employee_number": employee.employee_number,
        "employee_name": f"{employee.first_name} {employee.last_name}",
        "currency": profile.currency, "base_period_pay": str(profile.base_period_pay),
        "effective_from": profile.effective_from.isoformat(),
        "effective_to": profile.effective_to.isoformat() if profile.effective_to else None,
        "branch_id": profile.branch_id,
    } for profile, employee in rows]


@router.post("/hr/payroll/runs", status_code=201)
def create_hr_payroll_run(payload: HRPayrollRunIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    overlap = db.query(HRPayrollRun).filter(
        HRPayrollRun.organization_id == membership.organization_id,
        HRPayrollRun.period_start <= payload.period_end,
        HRPayrollRun.period_end >= payload.period_start,
    ).first()
    if overlap:
        raise HTTPException(409, f"Payroll period overlaps existing run {overlap.run_number}")
    employee_query = db.query(HREmployee).filter(
        HREmployee.organization_id == membership.organization_id,
        HREmployee.status == "active",
        HREmployee.start_date <= payload.period_end,
        or_(HREmployee.end_date.is_(None), HREmployee.end_date >= payload.period_start),
    )
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            raise HTTPException(403, "No branch access is assigned")
        employee_query = employee_query.filter(HREmployee.branch_id.in_(allowed))
    employees = employee_query.order_by(HREmployee.employee_number).all()
    if not employees:
        raise HTTPException(409, "No active employees are eligible for this payroll period")
    profiles = db.query(HRPayrollProfile).filter(
        HRPayrollProfile.organization_id == membership.organization_id,
        HRPayrollProfile.effective_from <= payload.period_start,
        or_(HRPayrollProfile.effective_to.is_(None),
            HRPayrollProfile.effective_to >= payload.period_end),
        HRPayrollProfile.employee_id.in_([employee.id for employee in employees]),
    ).all()
    profile_map = {}
    for profile in profiles:
        if profile.employee_id in profile_map:
            raise HTTPException(409, "An employee has multiple effective payroll profiles")
        profile_map[profile.employee_id] = profile
    missing = [employee.employee_number for employee in employees if employee.id not in profile_map]
    if missing:
        raise HTTPException(409, {"message": "Every eligible employee needs a profile covering the entire payroll period",
                                  "employees_missing_profiles": missing})
    currencies = {profile_map[employee.id].currency for employee in employees}
    if len(currencies) != 1:
        raise HTTPException(422, "A payroll run can contain only one currency; separate the workforce by currency")
    currency = next(iter(currencies))
    run = HRPayrollRun(
        organization_id=membership.organization_id,
        run_number="PAY-" + uuid.uuid4().hex[:12].upper(),
        period_start=payload.period_start, period_end=payload.period_end,
        pay_date=payload.pay_date, currency=currency, status="draft",
        created_by=user.id,
    )
    db.add(run)
    db.flush()
    gross_total = Decimal("0.00")
    for employee in employees:
        profile = profile_map[employee.id]
        base = payroll_money(profile.base_period_pay)
        gross_total += base
        db.add(HRPayrollLine(
            organization_id=membership.organization_id, run_id=run.id,
            employee_id=employee.id, branch_id=employee.branch_id,
            employee_number=employee.employee_number,
            employee_name=f"{employee.first_name} {employee.last_name}",
            department=employee.department, job_title=employee.job_title,
            base_pay=base, gross_pay=base, deductions_total=Decimal("0.00"),
            net_pay=base,
        ))
    run.gross_total = payroll_money(gross_total)
    run.deductions_total = Decimal("0.00")
    run.net_total = payroll_money(gross_total)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Payroll period conflicts with another run")
    db.refresh(run)
    audit(db, user.id, membership.organization_id, "hr.payroll.run.created",
          "hr_payroll_run", run.id, f"employees:{len(employees)};currency:{currency}")
    return {**_hr_payroll_run_out(run), "employee_count": len(employees)}


@router.get("/hr/payroll/runs")
def list_hr_payroll_runs(membership=Depends(active_membership), db: Session=Depends(get_db),
    limit: int=Query(default=100, ge=1, le=500)):
    require_permission(membership, "manage")
    runs = db.query(HRPayrollRun).filter_by(
        organization_id=membership.organization_id
    ).order_by(HRPayrollRun.period_start.desc(), HRPayrollRun.id.desc()).limit(limit).all()
    visible = []
    for run in runs:
        lines = db.query(HRPayrollLine).filter_by(
            organization_id=membership.organization_id, run_id=run.id
        ).all()
        if lines and all(can_access_branch(membership, line.branch_id) for line in lines):
            visible.append({**_hr_payroll_run_out(run), "employee_count": len(lines)})
    return visible


@router.get("/hr/payroll/runs/{run_id}")
def get_hr_payroll_run(run_id: int, membership=Depends(active_membership),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    run = db.query(HRPayrollRun).filter_by(
        id=run_id, organization_id=membership.organization_id
    ).first()
    if not run:
        raise HTTPException(404, "Payroll run not found")
    lines = _hr_payroll_run_lines(db, membership, run)
    result = []
    for line in lines:
        items = db.query(HRPayrollItem).filter_by(
            organization_id=membership.organization_id, payroll_line_id=line.id
        ).order_by(HRPayrollItem.id).all()
        result.append({
            "id": line.id, "employee_id": line.employee_id,
            "employee_number": line.employee_number, "employee_name": line.employee_name,
            "department": line.department, "job_title": line.job_title,
            "base_pay": str(line.base_pay), "gross_pay": str(line.gross_pay),
            "deductions_total": str(line.deductions_total), "net_pay": str(line.net_pay),
            "items": [{"id": item.id, "item_type": item.item_type, "code": item.code,
                       "description": item.description, "amount": str(item.amount)}
                      for item in items],
        })
    return {**_hr_payroll_run_out(run), "employee_count": len(lines), "lines": result}


@router.post("/hr/payroll/runs/{run_id}/items", status_code=201)
def add_hr_payroll_item(run_id: int, payload: HRPayrollItemIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    run = db.query(HRPayrollRun).filter_by(
        id=run_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not run:
        raise HTTPException(404, "Payroll run not found")
    if run.status != "draft":
        raise HTTPException(409, "Only draft payroll runs can be changed")
    line = db.query(HRPayrollLine).filter_by(
        organization_id=membership.organization_id, run_id=run.id,
        employee_id=payload.employee_id
    ).first()
    if not line or not can_access_branch(membership, line.branch_id):
        raise HTTPException(404, "Payroll employee line not found")
    request_hash = payroll_item_hash(payload)
    existing = db.query(HRPayrollItem).filter_by(
        organization_id=membership.organization_id, client_item_id=payload.client_item_id
    ).first()
    if existing:
        if existing.request_hash != request_hash or existing.run_id != run.id:
            raise HTTPException(409, "Payroll item ID was reused with different data")
        return {"id": existing.id, "status": "already_recorded",
                "gross_pay": str(line.gross_pay), "deductions_total": str(line.deductions_total),
                "net_pay": str(line.net_pay)}
    item = HRPayrollItem(
        organization_id=membership.organization_id, run_id=run.id,
        payroll_line_id=line.id, item_type=payload.item_type,
        code=payload.code.strip().upper(), description=payload.description.strip(),
        amount=payroll_money(payload.amount), client_item_id=payload.client_item_id,
        request_hash=request_hash, created_by=user.id,
    )
    items = db.query(HRPayrollItem).filter_by(
        organization_id=membership.organization_id, payroll_line_id=line.id
    ).all() + [item]
    try:
        gross, deductions, net = payroll_totals(line.base_pay, items)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    line.gross_pay, line.deductions_total, line.net_pay = gross, deductions, net
    previous_gross = Decimal(str(line.gross_pay))
    previous_deductions = Decimal(str(line.deductions_total))
    previous_net = Decimal(str(line.net_pay))
    db.add(item)
    all_lines = db.query(HRPayrollLine).filter_by(
        organization_id=membership.organization_id, run_id=run.id
    ).all()
    run.gross_total = payroll_money(sum((Decimal(str(x.gross_pay)) for x in all_lines), Decimal("0.00")) - previous_gross + gross)
    run.deductions_total = payroll_money(sum((Decimal(str(x.deductions_total)) for x in all_lines), Decimal("0.00")) - previous_deductions + deductions)
    run.net_total = payroll_money(sum((Decimal(str(x.net_pay)) for x in all_lines), Decimal("0.00")) - previous_net + net)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(HRPayrollItem).filter_by(
            organization_id=membership.organization_id, client_item_id=payload.client_item_id
        ).first()
        if existing and existing.request_hash == request_hash and existing.run_id == run.id:
            refreshed_line = db.query(HRPayrollLine).filter_by(
                organization_id=membership.organization_id, run_id=run.id,
                employee_id=payload.employee_id
            ).first()
            return {"id": existing.id, "status": "already_recorded",
                    "gross_pay": str(refreshed_line.gross_pay),
                    "deductions_total": str(refreshed_line.deductions_total),
                    "net_pay": str(refreshed_line.net_pay)}
        raise HTTPException(409, "Payroll item conflicts with an existing item ID")
    db.refresh(item)
    audit(db, user.id, membership.organization_id, "hr.payroll.item.added",
          "hr_payroll_item", item.id, f"run:{run.id};employee:{line.employee_id};type:{item.item_type}")
    return {"id": item.id, "status": "recorded", "gross_pay": str(line.gross_pay),
            "deductions_total": str(line.deductions_total), "net_pay": str(line.net_pay),
            "run_gross_total": str(run.gross_total), "run_net_total": str(run.net_total)}


@router.post("/hr/payroll/runs/{run_id}/approve")
def approve_hr_payroll_run(run_id: int, payload: HRPayrollApproveIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    run = db.query(HRPayrollRun).filter_by(
        id=run_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not run:
        raise HTTPException(404, "Payroll run not found")
    if run.status != "draft":
        raise HTTPException(409, "Only draft payroll runs can be approved")
    if run.created_by == user.id:
        raise HTTPException(403, "The payroll run creator cannot approve the same run")
    lines = _hr_payroll_run_lines(db, membership, run)
    if not lines or any(Decimal(str(line.net_pay)) < 0 for line in lines):
        raise HTTPException(409, "Payroll run contains an invalid net pay")
    run.status = "approved"
    run.approved_by = user.id
    run.approved_at = datetime.now(timezone.utc)
    run.approval_note = payload.note.strip()
    db.commit()
    audit(db, user.id, membership.organization_id, "hr.payroll.run.approved",
          "hr_payroll_run", run.id, f"employees:{len(lines)}")
    return _hr_payroll_run_out(run)


@router.get("/hr/payroll/my-payslips")
def list_my_hr_payslips(membership=Depends(active_membership),
    user: User=Depends(current_user), db: Session=Depends(get_db),
    limit: int=Query(default=24, ge=1, le=120)):
    require_permission(membership, "read")
    employee = db.query(HREmployee).filter_by(
        organization_id=membership.organization_id, user_id=user.id, status="active"
    ).first()
    if not employee or not can_access_branch(membership, employee.branch_id):
        return []
    q = db.query(HRPayrollLine, HRPayrollRun).join(
        HRPayrollRun, HRPayrollRun.id == HRPayrollLine.run_id
    ).filter(HRPayrollLine.organization_id == membership.organization_id,
             HRPayrollLine.employee_id == employee.id, HRPayrollRun.status == "approved")
    rows = q.order_by(HRPayrollRun.period_end.desc()).limit(limit).all()
    payslips = []
    for line, run in rows:
        items = db.query(HRPayrollItem).filter_by(
            organization_id=membership.organization_id, payroll_line_id=line.id
        ).order_by(HRPayrollItem.id).all()
        payslips.append({
            "run_number": run.run_number, "period_start": run.period_start.isoformat(),
            "period_end": run.period_end.isoformat(), "pay_date": run.pay_date.isoformat(),
            "currency": run.currency, "employee_number": line.employee_number,
            "employee_name": line.employee_name, "base_pay": str(line.base_pay),
            "gross_pay": str(line.gross_pay), "deductions_total": str(line.deductions_total),
            "net_pay": str(line.net_pay),
            "items": [{"item_type": item.item_type, "code": item.code,
                       "description": item.description, "amount": str(item.amount)}
                      for item in items],
        })
    return payslips




# Healthcare patient registration, scheduling and signed clinical encounter records.
def _healthcare_patient_out(row):
    return {
        "id": row.id, "patient_number": row.patient_number,
        "first_name": row.first_name, "last_name": row.last_name,
        "date_of_birth": row.date_of_birth.isoformat() if row.date_of_birth else None,
        "phone": row.phone, "email": row.email, "branch_id": row.branch_id,
        "emergency_contact_name": row.emergency_contact_name,
        "emergency_contact_phone": row.emergency_contact_phone,
    }


def _healthcare_datetime_out(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _healthcare_appointment_out(row, patient=None):
    return {
        "id": row.id, "patient_id": row.patient_id,
        "patient_number": patient.patient_number if patient else None,
        "patient_name": f"{patient.first_name} {patient.last_name}" if patient else None,
        "branch_id": row.branch_id, "provider_user_id": row.provider_user_id,
        "starts_at": _healthcare_datetime_out(row.starts_at), "ends_at": _healthcare_datetime_out(row.ends_at),
        "reason": row.reason, "status": row.status, "status_note": row.status_note,
    }


@router.post("/healthcare/patients", status_code=201)
def create_healthcare_patient(payload: HealthcarePatientIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    _crm_branch_check(db, membership, payload.branch_id)
    patient_number = payload.patient_number.strip().upper()
    if db.query(HealthcarePatient).filter_by(
        organization_id=membership.organization_id, patient_number=patient_number
    ).first():
        raise HTTPException(409, "Patient number already exists in this organization")
    row = HealthcarePatient(
        organization_id=membership.organization_id, branch_id=payload.branch_id,
        patient_number=patient_number, first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(), date_of_birth=payload.date_of_birth,
        phone=payload.phone.strip() if payload.phone else None,
        email=str(payload.email).lower() if payload.email else None,
        emergency_contact_name=payload.emergency_contact_name.strip(),
        emergency_contact_phone=payload.emergency_contact_phone.strip(),
        created_by=user.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Patient number conflicts with an existing patient")
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "healthcare.patient.created",
          "healthcare_patient", row.id)
    return _healthcare_patient_out(row)


@router.get("/healthcare/patients")
def list_healthcare_patients(q: str | None = None,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db), limit: int=Query(default=100, ge=1, le=500)):
    require_permission(membership, "manage")
    query = db.query(HealthcarePatient).filter_by(
        organization_id=membership.organization_id
    )
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            return []
        query = query.filter(HealthcarePatient.branch_id.in_(allowed))
    if q and q.strip():
        term = "%" + q.strip().replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.filter(or_(
            HealthcarePatient.patient_number.ilike(term),
            HealthcarePatient.first_name.ilike(term),
            HealthcarePatient.last_name.ilike(term),
            HealthcarePatient.phone.ilike(term),
        ))
    rows = query.order_by(HealthcarePatient.id.desc()).limit(limit).all()
    audit(db, user.id, membership.organization_id, "healthcare.patient.listed",
          "healthcare_patient", "search", f"count:{len(rows)}")
    return [_healthcare_patient_out(row) for row in rows]


@router.get("/healthcare/patients/{patient_id}")
def get_healthcare_patient(patient_id: int, membership=Depends(active_membership),
    user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(HealthcarePatient).filter_by(
        id=patient_id, organization_id=membership.organization_id
    ).first()
    if not row or not can_access_branch(membership, row.branch_id):
        raise HTTPException(404, "Patient not found")
    audit(db, user.id, membership.organization_id, "healthcare.patient.viewed",
          "healthcare_patient", row.id)
    return _healthcare_patient_out(row)


@router.post("/healthcare/appointments", status_code=201)
def create_healthcare_appointment(payload: HealthcareAppointmentIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    patient = db.query(HealthcarePatient).filter_by(
        id=payload.patient_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not patient or not can_access_branch(membership, patient.branch_id):
        raise HTTPException(404, "Patient not found")
    branch_id = payload.branch_id or patient.branch_id
    _crm_branch_check(db, membership, branch_id)
    provider_membership = db.query(Membership).filter_by(
        user_id=payload.provider_user_id, organization_id=membership.organization_id,
        is_active=True,
    ).with_for_update().first()
    if not provider_membership:
        raise HTTPException(404, "Provider is not an active organization member")
    provider_branches = branch_scope_ids(provider_membership)
    if provider_branches == []:
        raise HTTPException(403, "Provider has no active branch access")
    if branch_id and provider_branches is not None and branch_id not in provider_branches:
        raise HTTPException(403, "Provider is not assigned access to the appointment branch")
    starts_at = payload.starts_at.astimezone(timezone.utc)
    ends_at = payload.ends_at.astimezone(timezone.utc)
    if starts_at <= datetime.now(timezone.utc):
        raise HTTPException(422, "Appointments must be scheduled in the future")
    active_statuses = ["scheduled", "checked_in"]
    provider_conflict = db.query(HealthcareAppointment).filter(
        HealthcareAppointment.organization_id == membership.organization_id,
        HealthcareAppointment.provider_user_id == payload.provider_user_id,
        HealthcareAppointment.status.in_(active_statuses),
        HealthcareAppointment.starts_at < ends_at,
        HealthcareAppointment.ends_at > starts_at,
    ).first()
    if provider_conflict:
        raise HTTPException(409, "Provider already has an overlapping appointment")
    patient_conflict = db.query(HealthcareAppointment).filter(
        HealthcareAppointment.organization_id == membership.organization_id,
        HealthcareAppointment.patient_id == patient.id,
        HealthcareAppointment.status.in_(active_statuses),
        HealthcareAppointment.starts_at < ends_at,
        HealthcareAppointment.ends_at > starts_at,
    ).first()
    if patient_conflict:
        raise HTTPException(409, "Patient already has an overlapping appointment")
    row = HealthcareAppointment(
        organization_id=membership.organization_id, patient_id=patient.id,
        branch_id=branch_id, provider_user_id=payload.provider_user_id,
        starts_at=starts_at, ends_at=ends_at, reason=payload.reason.strip(),
        status="scheduled", created_by=user.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Appointment conflicts with an existing record")
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "healthcare.appointment.created",
          "healthcare_appointment", row.id, f"patient:{patient.id};provider:{payload.provider_user_id}")
    return _healthcare_appointment_out(row, patient)


@router.get("/healthcare/appointments")
def list_healthcare_appointments(status: str | None = None,
    starts_after: datetime | None = None, ends_before: datetime | None = None,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db), limit: int=Query(default=100, ge=1, le=500)):
    require_permission(membership, "manage")
    query = db.query(HealthcareAppointment, HealthcarePatient).join(
        HealthcarePatient, HealthcarePatient.id == HealthcareAppointment.patient_id
    ).filter(HealthcareAppointment.organization_id == membership.organization_id)
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            return []
        query = query.filter(HealthcareAppointment.branch_id.in_(allowed))
    if status:
        if status not in {"scheduled", "checked_in", "completed", "cancelled", "no_show"}:
            raise HTTPException(422, "Invalid appointment status")
        query = query.filter(HealthcareAppointment.status == status)
    if starts_after:
        if starts_after.tzinfo is None or starts_after.utcoffset() is None:
            raise HTTPException(422, "starts_after must include a timezone")
        query = query.filter(HealthcareAppointment.starts_at >= starts_after.astimezone(timezone.utc))
    if ends_before:
        if ends_before.tzinfo is None or ends_before.utcoffset() is None:
            raise HTTPException(422, "ends_before must include a timezone")
        query = query.filter(HealthcareAppointment.ends_at <= ends_before.astimezone(timezone.utc))
    rows = query.order_by(HealthcareAppointment.starts_at).limit(limit).all()
    audit(db, user.id, membership.organization_id, "healthcare.appointment.listed",
          "healthcare_appointment", "schedule", f"count:{len(rows)}")
    return [_healthcare_appointment_out(appointment, patient) for appointment, patient in rows]


@router.post("/healthcare/appointments/{appointment_id}/status")
def update_healthcare_appointment_status(appointment_id: int,
    payload: HealthcareAppointmentStatusIn, membership=Depends(active_membership),
    user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(HealthcareAppointment).filter_by(
        id=appointment_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not row or not can_access_branch(membership, row.branch_id):
        raise HTTPException(404, "Appointment not found")
    validate_appointment_transition(row.status, payload.status)
    if payload.status in {"cancelled", "no_show"} and len(payload.note.strip()) < 3:
        raise HTTPException(422, "A reason is required when cancelling or marking no-show")
    if payload.status == "completed":
        encounter = db.query(HealthcareEncounter).filter_by(
            organization_id=membership.organization_id, appointment_id=row.id,
            status="signed",
        ).first()
        if not encounter:
            raise HTTPException(409, "A signed clinical encounter is required before completing the visit")
    previous = row.status
    row.status = payload.status
    row.status_note = payload.note.strip()
    db.commit()
    audit(db, user.id, membership.organization_id, "healthcare.appointment.status_changed",
          "healthcare_appointment", row.id, f"{previous}->{row.status};reason_recorded:{bool(payload.note.strip())}")
    return {"id": row.id, "status": row.status}


@router.post("/healthcare/appointments/{appointment_id}/encounter", status_code=201)
def create_healthcare_encounter(appointment_id: int, payload: HealthcareEncounterIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    appointment = db.query(HealthcareAppointment).filter_by(
        id=appointment_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not appointment or not can_access_branch(membership, appointment.branch_id):
        raise HTTPException(404, "Appointment not found")
    if appointment.provider_user_id != user.id:
        raise HTTPException(403, "Only the assigned provider may create the clinical encounter")
    if appointment.status != "checked_in":
        raise HTTPException(409, "Patient must be checked in before an encounter is opened")
    existing = db.query(HealthcareEncounter).filter_by(
        organization_id=membership.organization_id, appointment_id=appointment.id
    ).first()
    if existing:
        raise HTTPException(409, "An encounter already exists for this appointment")
    row = HealthcareEncounter(
        organization_id=membership.organization_id, appointment_id=appointment.id,
        patient_id=appointment.patient_id, branch_id=appointment.branch_id,
        provider_user_id=appointment.provider_user_id,
        chief_complaint=payload.chief_complaint.strip(),
        clinical_notes=payload.clinical_notes.strip(), assessment=payload.assessment.strip(),
        plan=payload.plan.strip(), status="draft", created_by=user.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An encounter already exists for this appointment")
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "healthcare.encounter.created",
          "healthcare_encounter", row.id, f"appointment:{appointment.id}")
    return {"id": row.id, "appointment_id": appointment.id, "patient_id": row.patient_id,
            "status": row.status}


@router.get("/healthcare/appointments/{appointment_id}/encounter")
def get_healthcare_encounter(appointment_id: int, membership=Depends(active_membership),
    user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(HealthcareEncounter).filter_by(
        organization_id=membership.organization_id, appointment_id=appointment_id
    ).first()
    if not row or not can_access_branch(membership, row.branch_id):
        raise HTTPException(404, "Encounter not found")
    audit(db, user.id, membership.organization_id, "healthcare.encounter.viewed",
          "healthcare_encounter", row.id)
    return {
        "id": row.id, "appointment_id": row.appointment_id, "patient_id": row.patient_id,
        "provider_user_id": row.provider_user_id, "chief_complaint": row.chief_complaint,
        "clinical_notes": row.clinical_notes, "assessment": row.assessment,
        "plan": row.plan, "status": row.status,
        "signed_by": row.signed_by, "signed_at": _healthcare_datetime_out(row.signed_at) if row.signed_at else None,
    }


@router.post("/healthcare/encounters/{encounter_id}/sign")
def sign_healthcare_encounter(encounter_id: int, payload: HealthcareEncounterSignIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(HealthcareEncounter).filter_by(
        id=encounter_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not row or not can_access_branch(membership, row.branch_id):
        raise HTTPException(404, "Encounter not found")
    if row.provider_user_id != user.id:
        raise HTTPException(403, "Only the assigned provider may sign this encounter")
    if row.status != "draft":
        raise HTTPException(409, "Only draft encounters can be signed")
    row.status = "signed"
    row.signed_by = user.id
    row.signed_at = datetime.now(timezone.utc)
    db.commit()
    audit(db, user.id, membership.organization_id, "healthcare.encounter.signed",
          "healthcare_encounter", row.id, "signed")
    return {"id": row.id, "status": row.status, "signed_at": row.signed_at.isoformat()}




# Pharmacy catalogue and batch stock; laboratory order/sample/result validation.
def _pharmacy_medicine_out(row):
    return {
        "id": row.id, "inventory_product_id": row.inventory_product_id,
        "sku": row.sku, "generic_name": row.generic_name, "brand_name": row.brand_name,
        "strength": row.strength, "dosage_form": row.dosage_form,
        "route": row.route, "unit": row.unit, "is_controlled": row.is_controlled,
        "is_active": row.is_active,
    }


def _pharmacy_batch_out(batch, medicine):
    state = batch.status
    if state == "active" and batch.expiry_date < date.today():
        state = "expired"
    return {
        "id": batch.id, "medicine_id": medicine.id, "sku": medicine.sku,
        "medicine_name": medicine.generic_name, "branch_id": batch.branch_id,
        "batch_number": batch.batch_number, "expiry_date": batch.expiry_date.isoformat(),
        "received_quantity": str(batch.received_quantity),
        "remaining_quantity": str(batch.remaining_quantity),
        "unit_cost": str(batch.unit_cost), "selling_price": str(batch.selling_price),
        "status": state, "received_at": batch.received_at.isoformat(),
    }


@router.post("/pharmacy/medicines", status_code=201)
def create_pharmacy_medicine(payload: PharmacyMedicineIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    sku = payload.sku.strip().upper()
    if db.query(PharmacyMedicine).filter_by(
        organization_id=membership.organization_id, sku=sku
    ).first():
        raise HTTPException(409, "Medicine SKU already exists in this organization")
    if db.query(InventoryProduct).filter_by(
        organization_id=membership.organization_id, sku=sku
    ).first():
        raise HTTPException(409, "SKU is already used by another inventory product")
    product = InventoryProduct(
        organization_id=membership.organization_id, sku=sku,
        name=f"{payload.generic_name.strip()} {payload.strength.strip()}".strip(),
        description=f"{payload.brand_name.strip()} | {payload.dosage_form.strip()} | {payload.route.strip()}",
        unit=payload.unit.strip(), sale_price=payload.sale_price,
        is_active=True, created_by=user.id,
    )
    db.add(product)
    db.flush()
    row = PharmacyMedicine(
        organization_id=membership.organization_id, inventory_product_id=product.id,
        sku=sku, generic_name=payload.generic_name.strip(),
        brand_name=payload.brand_name.strip(), strength=payload.strength.strip(),
        dosage_form=payload.dosage_form.strip(), route=payload.route.strip().lower(),
        unit=payload.unit.strip(), is_controlled=payload.is_controlled,
        is_active=True, created_by=user.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Medicine SKU conflicts with an existing inventory item")
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "pharmacy.medicine.created",
          "pharmacy_medicine", row.id, f"sku:{sku};controlled:{payload.is_controlled}")
    return _pharmacy_medicine_out(row)


@router.get("/pharmacy/medicines")
def list_pharmacy_medicines(membership=Depends(active_membership), db: Session=Depends(get_db),
    limit: int=Query(default=200, ge=1, le=1000)):
    require_permission(membership, "read")
    rows = db.query(PharmacyMedicine).filter_by(
        organization_id=membership.organization_id, is_active=True
    ).order_by(PharmacyMedicine.generic_name, PharmacyMedicine.strength).limit(limit).all()
    return [_pharmacy_medicine_out(row) for row in rows]


@router.post("/pharmacy/medicines/{medicine_id}/batches", status_code=201)
def receive_pharmacy_batch(medicine_id: int, payload: PharmacyBatchIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    _crm_branch_check(db, membership, payload.branch_id)
    medicine = db.query(PharmacyMedicine).filter_by(
        id=medicine_id, organization_id=membership.organization_id, is_active=True
    ).first()
    if not medicine:
        raise HTTPException(404, "Active medicine not found")
    if payload.expiry_date <= date.today():
        raise HTTPException(422, "Expired or same-day-expiry stock cannot be received")
    request_hash = pharmacy_batch_hash(payload, medicine.id)
    existing = db.query(PharmacyBatch).filter_by(
        organization_id=membership.organization_id, client_batch_id=payload.client_batch_id
    ).first()
    if existing:
        if existing.request_hash != request_hash or existing.medicine_id != medicine.id:
            raise HTTPException(409, "Batch client ID was reused with different data")
        return {"id": existing.id, "status": "already_recorded",
                "remaining_quantity": str(existing.remaining_quantity)}
    batch_number = payload.batch_number.strip().upper()
    if db.query(PharmacyBatch).filter_by(
        organization_id=membership.organization_id, medicine_id=medicine.id,
        branch_id=payload.branch_id, batch_number=batch_number
    ).first():
        raise HTTPException(409, "Batch number already exists for this medicine and branch")
    key = "pharmacy-batch:" + hashlib.sha256(payload.client_batch_id.encode()).hexdigest()[:40]
    row = PharmacyBatch(
        organization_id=membership.organization_id, medicine_id=medicine.id,
        branch_id=payload.branch_id, batch_number=batch_number,
        client_batch_id=payload.client_batch_id, request_hash=request_hash,
        expiry_date=payload.expiry_date, received_quantity=payload.received_quantity,
        remaining_quantity=payload.received_quantity, unit_cost=payload.unit_cost,
        selling_price=payload.selling_price, status="active", received_by=user.id,
    )
    db.add(row)
    db.add(InventoryStockMovement(
        organization_id=membership.organization_id,
        product_id=medicine.inventory_product_id, branch_id=payload.branch_id,
        quantity_delta=payload.received_quantity, movement_type="receipt",
        reference=f"pharmacy-batch:{batch_number}", idempotency_key=key, created_by=user.id,
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(PharmacyBatch).filter_by(
            organization_id=membership.organization_id, client_batch_id=payload.client_batch_id
        ).first()
        if existing and existing.request_hash == request_hash and existing.medicine_id == medicine.id:
            return {"id": existing.id, "status": "already_recorded",
                    "remaining_quantity": str(existing.remaining_quantity)}
        raise HTTPException(409, "Batch receipt conflicts with an existing batch or stock movement")
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "pharmacy.batch.received",
          "pharmacy_batch", row.id, f"medicine:{medicine.id};qty:{payload.received_quantity};branch:{payload.branch_id}")
    return {"id": row.id, "status": "received", "remaining_quantity": str(row.remaining_quantity),
            "inventory_product_id": medicine.inventory_product_id}


@router.get("/pharmacy/batches")
def list_pharmacy_batches(medicine_id: int | None = None, branch_id: str | None = None,
    status: str | None = None, membership=Depends(active_membership),
    user: User=Depends(current_user), db: Session=Depends(get_db),
    limit: int=Query(default=200, ge=1, le=1000)):
    require_permission(membership, "read")
    query = db.query(PharmacyBatch, PharmacyMedicine).join(
        PharmacyMedicine, PharmacyMedicine.id == PharmacyBatch.medicine_id
    ).filter(PharmacyBatch.organization_id == membership.organization_id)
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            return []
        query = query.filter(PharmacyBatch.branch_id.in_(allowed))
    if branch_id:
        if not can_access_branch(membership, branch_id):
            raise HTTPException(404, "Branch not found")
        query = query.filter(PharmacyBatch.branch_id == branch_id)
    if medicine_id:
        query = query.filter(PharmacyBatch.medicine_id == medicine_id)
    if status == "expired":
        query = query.filter(PharmacyBatch.status == "active",
                             PharmacyBatch.expiry_date < date.today())
    elif status in {"active", "quarantined"}:
        query = query.filter(PharmacyBatch.status == status)
        if status == "active":
            query = query.filter(PharmacyBatch.expiry_date >= date.today())
    elif status:
        raise HTTPException(422, "Invalid batch status")
    rows = query.order_by(PharmacyBatch.expiry_date, PharmacyBatch.id).limit(limit).all()
    audit(db, user.id, membership.organization_id, "pharmacy.batch.listed",
          "pharmacy_batch", "batch-list", f"count:{len(rows)}")
    return [_pharmacy_batch_out(batch, medicine) for batch, medicine in rows]


@router.post("/pharmacy/batches/{batch_id}/quarantine")
def quarantine_pharmacy_batch(batch_id: int, payload: PharmacyBatchQuarantineIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(PharmacyBatch).filter_by(
        id=batch_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not row or not can_access_branch(membership, row.branch_id):
        raise HTTPException(404, "Batch not found")
    if row.status != "active":
        raise HTTPException(409, "Only active batches can be quarantined")
    row.status = "quarantined"
    db.commit()
    audit(db, user.id, membership.organization_id, "pharmacy.batch.quarantined",
          "pharmacy_batch", row.id, payload.reason.strip())
    return {"id": row.id, "status": row.status}


def _lab_order_out(order, patient):
    return {
        "id": order.id, "client_order_id": order.client_order_id,
        "encounter_id": order.encounter_id, "patient_id": order.patient_id,
        "patient_name": f"{patient.first_name} {patient.last_name}" if patient else None,
        "branch_id": order.branch_id, "ordering_provider_id": order.ordering_provider_id,
        "status": order.status, "created_at": order.created_at.isoformat(),
    }


@router.post("/lab/tests", status_code=201)
def create_laboratory_test(payload: LaboratoryTestIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    code = payload.code.strip().upper()
    if db.query(LaboratoryTest).filter_by(
        organization_id=membership.organization_id, code=code
    ).first():
        raise HTTPException(409, "Laboratory test code already exists")
    row = LaboratoryTest(
        organization_id=membership.organization_id, code=code,
        name=payload.name.strip(), specimen_type=payload.specimen_type.strip().lower(),
        unit=payload.unit.strip(), reference_range=payload.reference_range.strip(),
        turnaround_hours=payload.turnaround_hours, is_active=True, created_by=user.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Laboratory test code conflicts with an existing test")
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "lab.test.created",
          "laboratory_test", row.id, f"code:{row.code}")
    return {"id": row.id, "code": row.code, "name": row.name,
            "specimen_type": row.specimen_type, "unit": row.unit,
            "reference_range": row.reference_range,
            "turnaround_hours": row.turnaround_hours}


@router.get("/lab/tests")
def list_laboratory_tests(membership=Depends(active_membership), db: Session=Depends(get_db),
    limit: int=Query(default=200, ge=1, le=1000)):
    require_permission(membership, "read")
    rows = db.query(LaboratoryTest).filter_by(
        organization_id=membership.organization_id, is_active=True
    ).order_by(LaboratoryTest.name).limit(limit).all()
    return [{"id": row.id, "code": row.code, "name": row.name,
             "specimen_type": row.specimen_type, "unit": row.unit,
             "reference_range": row.reference_range,
             "turnaround_hours": row.turnaround_hours} for row in rows]


@router.post("/lab/orders", status_code=201)
def create_laboratory_order(payload: LaboratoryOrderIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    encounter = db.query(HealthcareEncounter).filter_by(
        id=payload.encounter_id, organization_id=membership.organization_id, status="signed"
    ).first()
    if not encounter or not can_access_branch(membership, encounter.branch_id):
        raise HTTPException(404, "Signed encounter not found")
    if encounter.provider_user_id != user.id:
        raise HTTPException(403, "Only the assigned provider may order laboratory tests")
    request_hash = laboratory_order_hash(payload)
    existing = db.query(LaboratoryOrder).filter_by(
        organization_id=membership.organization_id, client_order_id=payload.client_order_id
    ).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "Laboratory order ID was reused with different data")
        patient = db.query(HealthcarePatient).filter_by(
            id=existing.patient_id, organization_id=membership.organization_id
        ).first()
        return {**_lab_order_out(existing, patient), "status": "already_recorded"}
    tests = db.query(LaboratoryTest).filter(
        LaboratoryTest.organization_id == membership.organization_id,
        LaboratoryTest.is_active == True,
        LaboratoryTest.id.in_(payload.test_ids),
    ).all()
    if {test.id for test in tests} != set(payload.test_ids):
        raise HTTPException(404, "One or more active laboratory tests were not found")
    if len({test.specimen_type for test in tests}) != 1:
        raise HTTPException(422, "Tests requiring different specimen types must be placed in separate orders")
    row = LaboratoryOrder(
        organization_id=membership.organization_id, encounter_id=encounter.id,
        patient_id=encounter.patient_id, branch_id=encounter.branch_id,
        ordering_provider_id=user.id, client_order_id=payload.client_order_id,
        request_hash=request_hash, status="ordered", created_by=user.id,
    )
    db.add(row)
    db.flush()
    for test in tests:
        db.add(LaboratoryOrderLine(
            organization_id=membership.organization_id, order_id=row.id,
            test_id=test.id, test_code=test.code, test_name=test.name,
            specimen_type=test.specimen_type, result_unit=test.unit,
            reference_range_snapshot=test.reference_range, status="pending",
        ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(LaboratoryOrder).filter_by(
            organization_id=membership.organization_id, client_order_id=payload.client_order_id
        ).first()
        if existing and existing.request_hash == request_hash:
            patient = db.query(HealthcarePatient).filter_by(
                id=existing.patient_id, organization_id=membership.organization_id
            ).first()
            return {**_lab_order_out(existing, patient), "status": "already_recorded"}
        raise HTTPException(409, "Laboratory order conflicts with an existing order")
    db.refresh(row)
    patient = db.query(HealthcarePatient).filter_by(
        id=row.patient_id, organization_id=membership.organization_id
    ).first()
    audit(db, user.id, membership.organization_id, "lab.order.created",
          "laboratory_order", row.id, f"encounter:{encounter.id};tests:{len(tests)}")
    return {**_lab_order_out(row, patient), "status": "ordered"}


@router.get("/lab/orders")
def list_laboratory_orders(status: str | None = None,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db), limit: int=Query(default=100, ge=1, le=500)):
    require_permission(membership, "manage")
    query = db.query(LaboratoryOrder, HealthcarePatient).join(
        HealthcarePatient, HealthcarePatient.id == LaboratoryOrder.patient_id
    ).filter(LaboratoryOrder.organization_id == membership.organization_id)
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            return []
        query = query.filter(LaboratoryOrder.branch_id.in_(allowed))
    if status:
        if status not in {"ordered", "sample_collected", "processing", "results_entered", "validated"}:
            raise HTTPException(422, "Invalid laboratory order status")
        query = query.filter(LaboratoryOrder.status == status)
    rows = query.order_by(LaboratoryOrder.created_at.desc()).limit(limit).all()
    audit(db, user.id, membership.organization_id, "lab.order.listed",
          "laboratory_order", "order-list", f"count:{len(rows)}")
    return [_lab_order_out(order, patient) for order, patient in rows]


@router.get("/lab/orders/{order_id}")
def get_laboratory_order(order_id: int, membership=Depends(active_membership),
    user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    order = db.query(LaboratoryOrder).filter_by(
        id=order_id, organization_id=membership.organization_id
    ).first()
    if not order or not can_access_branch(membership, order.branch_id):
        raise HTTPException(404, "Laboratory order not found")
    patient = db.query(HealthcarePatient).filter_by(
        id=order.patient_id, organization_id=membership.organization_id
    ).first()
    sample = db.query(LaboratorySample).filter_by(
        organization_id=membership.organization_id, order_id=order.id
    ).first()
    lines = db.query(LaboratoryOrderLine).filter_by(
        organization_id=membership.organization_id, order_id=order.id
    ).order_by(LaboratoryOrderLine.id).all()
    audit(db, user.id, membership.organization_id, "lab.order.viewed",
          "laboratory_order", order.id)
    return {
        **_lab_order_out(order, patient),
        "sample": ({"accession_number": sample.accession_number,
                    "specimen_type": sample.specimen_type, "status": sample.status,
                    "collected_at": sample.collected_at.isoformat()} if sample else None),
        "lines": [{
            "id": line.id, "test_id": line.test_id, "test_code": line.test_code,
            "test_name": line.test_name, "specimen_type": line.specimen_type,
            "result_unit": line.result_unit,
            "reference_range": line.reference_range_snapshot,
            "result_value": line.result_value, "result_notes": line.result_notes,
            "status": line.status, "entered_by": line.entered_by,
            "validated_by": line.validated_by,
            "validated_at": line.validated_at.isoformat() if line.validated_at else None,
        } for line in lines],
    }


@router.post("/lab/orders/{order_id}/sample", status_code=201)
def collect_laboratory_sample(order_id: int, payload: LaboratorySampleIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    order = db.query(LaboratoryOrder).filter_by(
        id=order_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not order or not can_access_branch(membership, order.branch_id):
        raise HTTPException(404, "Laboratory order not found")
    existing = db.query(LaboratorySample).filter_by(
        organization_id=membership.organization_id, order_id=order.id
    ).first()
    if existing:
        if (existing.accession_number == payload.accession_number.strip().upper()
                and existing.specimen_type == payload.specimen_type.strip().lower()):
            return {"id": existing.id, "order_id": order.id,
                    "accession_number": existing.accession_number,
                    "specimen_type": existing.specimen_type, "status": "already_recorded"}
        raise HTTPException(409, "A different sample is already registered for this order")
    if order.status != "ordered":
        raise HTTPException(409, "Only newly ordered tests can have a sample collected")
    lines = db.query(LaboratoryOrderLine).filter_by(
        organization_id=membership.organization_id, order_id=order.id
    ).all()
    if not lines or any(line.specimen_type != payload.specimen_type.strip().lower() for line in lines):
        raise HTTPException(422, "Sample specimen type does not match every ordered test")
    row = LaboratorySample(
        organization_id=membership.organization_id, order_id=order.id,
        accession_number=payload.accession_number.strip().upper(),
        specimen_type=payload.specimen_type.strip().lower(),
        status="collected", collected_at=datetime.now(timezone.utc), collected_by=user.id,
    )
    db.add(row)
    order.status = "sample_collected"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Accession number or sample already exists")
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "lab.sample.collected",
          "laboratory_sample", row.id, f"order:{order.id}")
    return {"id": row.id, "order_id": order.id, "accession_number": row.accession_number,
            "specimen_type": row.specimen_type, "status": row.status}


@router.post("/lab/orders/{order_id}/lines/{line_id}/result")
def enter_laboratory_result(order_id: int, line_id: int, payload: LaboratoryResultIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    order = db.query(LaboratoryOrder).filter_by(
        id=order_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not order or not can_access_branch(membership, order.branch_id):
        raise HTTPException(404, "Laboratory order not found")
    if order.status not in {"sample_collected", "processing"}:
        raise HTTPException(409, "Results can only be entered after sample collection and before validation")
    line = db.query(LaboratoryOrderLine).filter_by(
        id=line_id, organization_id=membership.organization_id, order_id=order.id
    ).with_for_update().first()
    if not line:
        raise HTTPException(404, "Laboratory order line not found")
    if line.status != "pending":
        raise HTTPException(409, "A result has already been entered for this test")
    line.result_value = payload.result_value.strip()
    line.result_notes = payload.result_notes.strip()
    line.entered_by = user.id
    line.status = "entered"
    lines = db.query(LaboratoryOrderLine).filter_by(
        organization_id=membership.organization_id, order_id=order.id
    ).all()
    order.status = "results_entered" if all(x.status == "entered" for x in lines) else "processing"
    db.commit()
    audit(db, user.id, membership.organization_id, "lab.result.entered",
          "laboratory_order_line", line.id, f"order:{order.id}")
    return {"id": line.id, "status": line.status, "order_status": order.status}


@router.post("/lab/orders/{order_id}/validate")
def validate_laboratory_order(order_id: int, payload: LaboratoryValidateIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    order = db.query(LaboratoryOrder).filter_by(
        id=order_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not order or not can_access_branch(membership, order.branch_id):
        raise HTTPException(404, "Laboratory order not found")
    if order.status != "results_entered":
        raise HTTPException(409, "Every test result must be entered before validation")
    lines = db.query(LaboratoryOrderLine).filter_by(
        organization_id=membership.organization_id, order_id=order.id
    ).with_for_update().all()
    if not lines or any(line.status != "entered" or not line.result_value.strip() for line in lines):
        raise HTTPException(409, "Laboratory order has missing results")
    if any(line.entered_by == user.id for line in lines):
        raise HTTPException(403, "A result author cannot validate their own laboratory order")
    now_utc = datetime.now(timezone.utc)
    for line in lines:
        line.status = "validated"
        line.validated_by = user.id
        line.validated_at = now_utc
    order.status = "validated"
    db.commit()
    audit(db, user.id, membership.organization_id, "lab.order.validated",
          "laboratory_order", order.id, "independent validation completed")
    return {"id": order.id, "status": order.status,
            "validated_lines": len(lines), "note_recorded": bool(payload.note.strip())}


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



# SACCO member, savings and loan-origination APIs.
def _sacco_member_or_404(db, membership, member_id):
    member = db.query(SaccoMember).filter_by(
        id=member_id, organization_id=membership.organization_id
    ).first()
    if not member or (member.branch_id and not can_access_branch(membership, member.branch_id)):
        raise HTTPException(404, "SACCO member not found")
    return member


def _sacco_account_balance(db, organization_id, account_id):
    rows = db.query(SaccoTransaction.transaction_type, SaccoTransaction.amount).filter_by(
        organization_id=organization_id, account_id=account_id
    ).all()
    balance = Decimal("0.00")
    for transaction_type, amount in rows:
        amount = Decimal(str(amount))
        if transaction_type == "withdrawal":
            balance -= amount
        else:
            balance += amount
    return balance.quantize(Decimal("0.01"))


@router.post("/sacco/members", status_code=201)
def create_sacco_member(payload: SaccoMemberIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "create")
    if payload.branch_id:
        branch = db.query(Branch).filter_by(
            id=payload.branch_id, organization_id=membership.organization_id, is_active=True
        ).first()
        if not branch or not can_access_branch(membership, branch.id):
            raise HTTPException(404, "Branch not found")
    row = SaccoMember(organization_id=membership.organization_id,
        branch_id=payload.branch_id, member_number=payload.member_number.strip(),
        full_name=payload.full_name.strip(), phone=payload.phone, email=payload.email,
        status="pending", kyc_status="pending", created_by=user.id)
    db.add(row)
    db.add(AuditEvent(actor_user_id=user.id, organization_id=membership.organization_id,
        action="sacco.member.created", resource_type="sacco_member",
        resource_id=payload.member_number, detail="KYC pending"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Member number already exists in this organization")
    db.refresh(row)
    return {"id": row.id, "member_number": row.member_number, "full_name": row.full_name,
        "status": row.status, "kyc_status": row.kyc_status, "branch_id": row.branch_id}


@router.get("/sacco/members")
def list_sacco_members(membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    rows = db.query(SaccoMember).filter_by(
        organization_id=membership.organization_id
    ).order_by(SaccoMember.created_at.desc(), SaccoMember.id.desc()).all()
    return [{"id": row.id, "member_number": row.member_number, "full_name": row.full_name,
        "phone": row.phone, "email": row.email, "status": row.status,
        "kyc_status": row.kyc_status, "branch_id": row.branch_id,
        "created_at": row.created_at.isoformat()} for row in rows
        if not row.branch_id or can_access_branch(membership, row.branch_id)]


@router.post("/sacco/members/{member_id}/kyc-decision")
def decide_sacco_member_kyc(member_id: int, payload: SaccoKYCDecisionIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    member = _sacco_member_or_404(db, membership, member_id)
    if member.kyc_status != "pending":
        raise HTTPException(409, "KYC has already been decided")
    member.kyc_status = payload.decision
    member.status = "active" if payload.decision == "verified" else "rejected"
    member.reviewed_by = user.id
    member.reviewed_at = datetime.now(timezone.utc)
    member.review_note = payload.note.strip()
    db.add(AuditEvent(actor_user_id=user.id, organization_id=membership.organization_id,
        action="sacco.member.kyc_decided", resource_type="sacco_member",
        resource_id=member.id, detail=f"{payload.decision}:{payload.note.strip()}"))
    db.commit()
    return {"id": member.id, "status": member.status, "kyc_status": member.kyc_status}


@router.post("/sacco/accounts", status_code=201)
def create_sacco_account(payload: SaccoAccountIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    member = _sacco_member_or_404(db, membership, payload.member_id)
    if member.status != "active" or member.kyc_status != "verified":
        raise HTTPException(409, "Member must pass KYC before opening an account")
    account_number = f"SAC-{membership.organization_id}-{uuid.uuid4().hex[:10].upper()}"
    row = SaccoAccount(organization_id=membership.organization_id,
        member_id=member.id, branch_id=member.branch_id, account_number=account_number,
        account_type=payload.account_type, currency=payload.currency,
        status="active", created_by=user.id)
    db.add(row)
    db.add(AuditEvent(actor_user_id=user.id, organization_id=membership.organization_id,
        action="sacco.account.opened", resource_type="sacco_account",
        resource_id=account_number, detail=f"member:{member.id};type:{payload.account_type}"))
    db.commit()
    db.refresh(row)
    return {"id": row.id, "account_number": row.account_number, "member_id": row.member_id,
        "account_type": row.account_type, "currency": row.currency, "status": row.status,
        "balance": "0.00"}


@router.get("/sacco/accounts")
def list_sacco_accounts(member_id: int | None = None,
    membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    query = db.query(SaccoAccount).filter_by(organization_id=membership.organization_id)
    if member_id is not None:
        member = _sacco_member_or_404(db, membership, member_id)
        query = query.filter(SaccoAccount.member_id == member.id)
    rows = query.order_by(SaccoAccount.created_at.desc(), SaccoAccount.id.desc()).all()
    result = []
    for row in rows:
        if row.branch_id and not can_access_branch(membership, row.branch_id):
            continue
        result.append({"id": row.id, "account_number": row.account_number,
            "member_id": row.member_id, "account_type": row.account_type,
            "currency": row.currency, "status": row.status,
            "balance": str(_sacco_account_balance(db, membership.organization_id, row.id))})
    return result


@router.post("/sacco/accounts/{account_id}/transactions", status_code=201)
def post_sacco_transaction(account_id: int, payload: SaccoTransactionIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "create")
    account = db.query(SaccoAccount).filter_by(
        id=account_id, organization_id=membership.organization_id, status="active"
    ).with_for_update().first()
    if not account or (account.branch_id and not can_access_branch(membership, account.branch_id)):
        raise HTTPException(404, "Active SACCO account not found")
    member = _sacco_member_or_404(db, membership, account.member_id)
    if member.status != "active" or member.kyc_status != "verified":
        raise HTTPException(409, "Member KYC is not active")
    expected_type = {"savings": {"deposit", "withdrawal"},
        "shares": {"share_contribution"}, "contributions": {"contribution"}}
    if payload.transaction_type not in expected_type[account.account_type]:
        raise HTTPException(422, "Transaction type does not match the account type")
    if payload.transaction_type == "withdrawal":
        require_permission(membership, "manage")
    amount = Decimal(str(payload.amount)).quantize(Decimal("0.01"))
    request_body = {"account_id": account.id, "transaction_type": payload.transaction_type,
        "amount": str(amount), "reference": payload.reference.strip()}
    request_hash = hashlib.sha256(json.dumps(request_body, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    existing = db.query(SaccoTransaction).filter_by(
        organization_id=membership.organization_id,
        idempotency_key=payload.idempotency_key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "Idempotency key was used for different transaction data")
        return {"id": existing.id, "account_id": account.id, "status": "already_recorded",
            "balance": str(_sacco_account_balance(db, membership.organization_id, account.id))}
    balance = _sacco_account_balance(db, membership.organization_id, account.id)
    if payload.transaction_type == "withdrawal" and amount > balance:
        raise HTTPException(422, "Withdrawal exceeds available savings balance")
    row = SaccoTransaction(organization_id=membership.organization_id,
        account_id=account.id, transaction_type=payload.transaction_type,
        amount=amount, reference=payload.reference.strip(),
        idempotency_key=payload.idempotency_key, request_hash=request_hash,
        created_by=user.id)
    db.add(row)
    db.add(AuditEvent(actor_user_id=user.id, organization_id=membership.organization_id,
        action=f"sacco.transaction.{payload.transaction_type}", resource_type="sacco_account",
        resource_id=account.id, detail=f"amount:{amount};reference:{payload.reference.strip()}"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(SaccoTransaction).filter_by(
            organization_id=membership.organization_id,
            idempotency_key=payload.idempotency_key).first()
        if existing and existing.request_hash == request_hash:
            return {"id": existing.id, "account_id": account.id, "status": "already_recorded",
                "balance": str(_sacco_account_balance(db, membership.organization_id, account.id))}
        raise HTTPException(409, "Concurrent transaction conflicts with this idempotency key")
    db.refresh(row)
    return {"id": row.id, "account_id": account.id, "transaction_type": row.transaction_type,
        "amount": str(row.amount), "balance": str(_sacco_account_balance(db, membership.organization_id, account.id)),
        "status": "recorded"}


@router.get("/sacco/accounts/{account_id}/transactions")
def list_sacco_transactions(account_id: int,
    membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    account = db.query(SaccoAccount).filter_by(
        id=account_id, organization_id=membership.organization_id).first()
    if not account or (account.branch_id and not can_access_branch(membership, account.branch_id)):
        raise HTTPException(404, "SACCO account not found")
    rows = db.query(SaccoTransaction).filter_by(
        organization_id=membership.organization_id, account_id=account.id
    ).order_by(SaccoTransaction.created_at, SaccoTransaction.id).all()
    balance = Decimal("0.00")
    result = []
    for row in rows:
        amount = Decimal(str(row.amount))
        balance += -amount if row.transaction_type == "withdrawal" else amount
        result.append({"id": row.id, "transaction_type": row.transaction_type,
            "amount": str(row.amount), "reference": row.reference,
            "created_at": row.created_at.isoformat(), "running_balance": str(balance)})
    return {"account_id": account.id, "currency": account.currency,
        "balance": str(balance), "transactions": result}


@router.post("/sacco/loan-products", status_code=201)
def create_sacco_loan_product(payload: SaccoLoanProductIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    row = SaccoLoanProduct(organization_id=membership.organization_id,
        code=payload.code.strip(), name=payload.name.strip(),
        minimum_principal=payload.minimum_principal, maximum_principal=payload.maximum_principal,
        annual_interest_rate=payload.annual_interest_rate,
        minimum_term_months=payload.minimum_term_months, maximum_term_months=payload.maximum_term_months,
        interest_method=payload.interest_method, requires_guarantor=payload.requires_guarantor,
        is_active=True, created_by=user.id)
    db.add(row)
    db.add(AuditEvent(actor_user_id=user.id, organization_id=membership.organization_id,
        action="sacco.loan_product.created", resource_type="sacco_loan_product",
        resource_id=payload.code, detail=payload.name))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Loan product code already exists")
    db.refresh(row)
    return {"id": row.id, "code": row.code, "name": row.name,
        "minimum_principal": str(row.minimum_principal), "maximum_principal": str(row.maximum_principal),
        "annual_interest_rate": str(row.annual_interest_rate), "interest_method": row.interest_method,
        "requires_guarantor": row.requires_guarantor, "is_active": row.is_active}


@router.get("/sacco/loan-products")
def list_sacco_loan_products(membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    rows = db.query(SaccoLoanProduct).filter_by(
        organization_id=membership.organization_id, is_active=True
    ).order_by(SaccoLoanProduct.name).all()
    return [{"id": row.id, "code": row.code, "name": row.name,
        "minimum_principal": str(row.minimum_principal), "maximum_principal": str(row.maximum_principal),
        "annual_interest_rate": str(row.annual_interest_rate), "minimum_term_months": row.minimum_term_months,
        "maximum_term_months": row.maximum_term_months, "interest_method": row.interest_method,
        "requires_guarantor": row.requires_guarantor} for row in rows]


@router.post("/sacco/loan-applications", status_code=201)
def create_sacco_loan_application(payload: SaccoLoanApplicationIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "create")
    member = _sacco_member_or_404(db, membership, payload.member_id)
    if member.status != "active" or member.kyc_status != "verified":
        raise HTTPException(409, "Member must pass KYC before applying for a loan")
    product = db.query(SaccoLoanProduct).filter_by(
        id=payload.loan_product_id, organization_id=membership.organization_id, is_active=True
    ).first()
    if not product:
        raise HTTPException(404, "Active loan product not found")
    if product.requires_guarantor:
        raise HTTPException(422, "This product requires guarantor capture, which is not yet supported")
    principal = Decimal(str(payload.requested_principal)).quantize(Decimal("0.01"))
    if principal < product.minimum_principal or principal > product.maximum_principal:
        raise HTTPException(422, "Requested principal is outside loan product limits")
    if not product.minimum_term_months <= payload.term_months <= product.maximum_term_months:
        raise HTTPException(422, "Requested term is outside loan product limits")
    application_number = f"LA-{membership.organization_id}-{uuid.uuid4().hex[:12].upper()}"
    row = SaccoLoanApplication(organization_id=membership.organization_id,
        member_id=member.id, loan_product_id=product.id, branch_id=member.branch_id,
        application_number=application_number, requested_principal=principal,
        term_months=payload.term_months, purpose=payload.purpose.strip(),
        status="submitted", created_by=user.id)
    db.add(row)
    db.add(AuditEvent(actor_user_id=user.id, organization_id=membership.organization_id,
        action="sacco.loan_application.submitted", resource_type="sacco_loan_application",
        resource_id=application_number, detail=f"principal:{principal};term:{payload.term_months}"))
    db.commit()
    db.refresh(row)
    return {"id": row.id, "application_number": row.application_number,
        "requested_principal": str(row.requested_principal), "term_months": row.term_months,
        "status": row.status}


@router.get("/sacco/loan-applications")
def list_sacco_loan_applications(status: str | None = None,
    membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    query = db.query(SaccoLoanApplication).filter_by(organization_id=membership.organization_id)
    if status:
        if status not in {"submitted", "approved", "rejected"}:
            raise HTTPException(422, "Invalid application status filter")
        query = query.filter(SaccoLoanApplication.status == status)
    rows = query.order_by(SaccoLoanApplication.created_at.desc()).all()
    result = []
    for row in rows:
        if row.branch_id and not can_access_branch(membership, row.branch_id):
            continue
        result.append({"id": row.id, "application_number": row.application_number,
            "member_id": row.member_id, "loan_product_id": row.loan_product_id,
            "requested_principal": str(row.requested_principal), "term_months": row.term_months,
            "purpose": row.purpose, "status": row.status, "review_note": row.review_note,
            "created_at": row.created_at.isoformat()})
    return result


@router.post("/sacco/loan-applications/{application_id}/decision")
def decide_sacco_loan_application(application_id: int, payload: SaccoLoanDecisionIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(SaccoLoanApplication).filter_by(
        id=application_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not row or (row.branch_id and not can_access_branch(membership, row.branch_id)):
        raise HTTPException(404, "Loan application not found")
    if row.status != "submitted":
        raise HTTPException(409, "Loan application has already been decided")
    if row.created_by == user.id:
        raise HTTPException(403, "The loan applicant cannot approve their own application")
    row.status = payload.decision
    row.reviewed_by = user.id
    row.reviewed_at = datetime.now(timezone.utc)
    row.review_note = payload.note.strip()
    db.add(AuditEvent(actor_user_id=user.id, organization_id=membership.organization_id,
        action=f"sacco.loan_application.{payload.decision}", resource_type="sacco_loan_application",
        resource_id=row.application_number, detail=payload.note.strip()))
    db.commit()
    return {"id": row.id, "application_number": row.application_number,
        "status": row.status, "reviewed_by": row.reviewed_by,
        "review_note": row.review_note}


@router.post("/sacco/loan-applications/{application_id}/disburse", status_code=201)
def disburse_sacco_loan(application_id: int, payload: SaccoLoanDisbursementIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    """Record an approved loan disbursement and generate its contractual schedule."""
    require_permission(membership, "manage")
    application = db.query(SaccoLoanApplication).filter_by(
        id=application_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not application or (application.branch_id and not can_access_branch(membership, application.branch_id)):
        raise HTTPException(404, "Loan application not found")
    existing = db.query(SaccoLoan).filter_by(
        organization_id=membership.organization_id, application_id=application.id
    ).first()
    if existing:
        return {"id": existing.id, "loan_number": existing.loan_number,
            "status": "already_disbursed", "funds_transfer_executed": False}
    if application.status != "approved":
        raise HTTPException(409, "Only approved loan applications may be disbursed")
    if application.created_by == user.id:
        raise HTTPException(403, "The loan applicant cannot disburse their own loan")
    product = db.query(SaccoLoanProduct).filter_by(
        id=application.loan_product_id, organization_id=membership.organization_id,
        is_active=True).first()
    if not product:
        raise HTTPException(409, "The originating loan product is no longer active")
    if product.requires_guarantor:
        raise HTTPException(409, "Guarantor verification is not available for this product")
    disbursed_at = datetime.now(timezone.utc)
    first_due_date = add_months(disbursed_at.date(), 1)
    try:
        schedule = build_repayment_schedule(
            application.requested_principal, product.annual_interest_rate,
            application.term_months, product.interest_method, first_due_date)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    total_interest = sacco_money(sum((item["interest_due"] for item in schedule), Decimal("0.00")))
    loan_number = f"LN-{membership.organization_id}-{uuid.uuid4().hex[:12].upper()}"
    loan = SaccoLoan(organization_id=membership.organization_id,
        application_id=application.id, member_id=application.member_id,
        branch_id=application.branch_id, loan_number=loan_number,
        principal=application.requested_principal,
        annual_interest_rate=product.annual_interest_rate,
        term_months=application.term_months, interest_method=product.interest_method,
        total_interest=total_interest, outstanding_principal=application.requested_principal,
        outstanding_interest=total_interest, status="active",
        disbursement_reference=payload.reference, disbursed_at=disbursed_at,
        created_by=user.id)
    db.add(loan)
    db.flush()
    for item in schedule:
        db.add(SaccoLoanSchedule(organization_id=membership.organization_id,
            loan_id=loan.id, installment_number=item["installment_number"],
            due_date=item["due_date"], principal_due=item["principal_due"],
            interest_due=item["interest_due"], principal_paid=Decimal("0.00"),
            interest_paid=Decimal("0.00"), status="pending"))
    db.add(AuditEvent(actor_user_id=user.id, organization_id=membership.organization_id,
        action="sacco.loan.disbursement_recorded", resource_type="sacco_loan",
        resource_id=loan_number, detail=f"application:{application.application_number};principal:{loan.principal};reference:{payload.reference}"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(SaccoLoan).filter_by(
            organization_id=membership.organization_id, application_id=application.id).first()
        if existing:
            return {"id": existing.id, "loan_number": existing.loan_number,
                "status": "already_disbursed", "funds_transfer_executed": False}
        raise HTTPException(409, "Loan disbursement conflicted with another request")
    db.refresh(loan)
    return {"id": loan.id, "loan_number": loan.loan_number, "status": loan.status,
        "principal": str(loan.principal), "total_interest": str(loan.total_interest),
        "installments": len(schedule), "first_due_date": schedule[0]["due_date"].isoformat(),
        "disbursement_reference": loan.disbursement_reference,
        "funds_transfer_executed": False}


@router.get("/sacco/loans")
def list_sacco_loans(status: str | None = None,
    membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    query = db.query(SaccoLoan).filter_by(organization_id=membership.organization_id)
    if status:
        if status not in {"active", "closed"}:
            raise HTTPException(422, "Invalid loan status filter")
        query = query.filter(SaccoLoan.status == status)
    rows = query.order_by(SaccoLoan.disbursed_at.desc()).all()
    return [{"id": row.id, "loan_number": row.loan_number, "member_id": row.member_id,
        "application_id": row.application_id, "principal": str(row.principal),
        "total_interest": str(row.total_interest),
        "outstanding_principal": str(row.outstanding_principal),
        "outstanding_interest": str(row.outstanding_interest),
        "term_months": row.term_months, "interest_method": row.interest_method,
        "status": row.status, "disbursed_at": row.disbursed_at.isoformat()}
        for row in rows if not row.branch_id or can_access_branch(membership, row.branch_id)]


@router.get("/sacco/loans/{loan_id}/schedule")
def get_sacco_loan_schedule(loan_id: int,
    membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    loan = db.query(SaccoLoan).filter_by(
        id=loan_id, organization_id=membership.organization_id).first()
    if not loan or (loan.branch_id and not can_access_branch(membership, loan.branch_id)):
        raise HTTPException(404, "SACCO loan not found")
    rows = db.query(SaccoLoanSchedule).filter_by(
        organization_id=membership.organization_id, loan_id=loan.id
    ).order_by(SaccoLoanSchedule.installment_number).all()
    return {"loan_id": loan.id, "loan_number": loan.loan_number,
        "currency": "KES", "status": loan.status,
        "outstanding_principal": str(loan.outstanding_principal),
        "outstanding_interest": str(loan.outstanding_interest),
        "installments": [{"number": row.installment_number, "due_date": row.due_date.isoformat(),
            "principal_due": str(row.principal_due), "interest_due": str(row.interest_due),
            "principal_paid": str(row.principal_paid), "interest_paid": str(row.interest_paid),
            "status": row.status} for row in rows]}


@router.post("/sacco/loans/{loan_id}/repayments", status_code=201)
def record_sacco_loan_repayment(loan_id: int, payload: SaccoLoanRepaymentIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "create")
    loan = db.query(SaccoLoan).filter_by(
        id=loan_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not loan or (loan.branch_id and not can_access_branch(membership, loan.branch_id)):
        raise HTTPException(404, "SACCO loan not found")
    amount = sacco_money(payload.amount)
    request_data = {"loan_id": loan.id, "amount": str(amount), "reference": payload.reference.strip()}
    request_hash = hashlib.sha256(json.dumps(request_data, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    existing = db.query(SaccoLoanRepayment).filter_by(
        organization_id=membership.organization_id,
        idempotency_key=payload.idempotency_key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "Idempotency key was used for different repayment data")
        return {"id": existing.id, "loan_id": loan.id, "status": "already_recorded",
            "amount": str(existing.amount), "outstanding_principal": str(loan.outstanding_principal),
            "outstanding_interest": str(loan.outstanding_interest)}
    if loan.status != "active":
        raise HTTPException(409, "Only active loans can receive repayments")
    rows = db.query(SaccoLoanSchedule).filter_by(
        organization_id=membership.organization_id, loan_id=loan.id
    ).order_by(SaccoLoanSchedule.installment_number).with_for_update().all()
    try:
        principal_component, interest_component, allocations = allocate_repayment(amount, rows)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if not allocations:
        raise HTTPException(409, "Loan has no outstanding installments")
    for schedule_row, interest_part, principal_part in allocations:
        schedule_row.interest_paid = sacco_money(Decimal(str(schedule_row.interest_paid)) + interest_part)
        schedule_row.principal_paid = sacco_money(Decimal(str(schedule_row.principal_paid)) + principal_part)
        if schedule_row.interest_paid >= schedule_row.interest_due and schedule_row.principal_paid >= schedule_row.principal_due:
            schedule_row.status = "paid"
        elif schedule_row.interest_paid > 0 or schedule_row.principal_paid > 0:
            schedule_row.status = "partial"
    loan.outstanding_principal = sacco_money(Decimal(str(loan.outstanding_principal)) - principal_component)
    loan.outstanding_interest = sacco_money(Decimal(str(loan.outstanding_interest)) - interest_component)
    if loan.outstanding_principal == 0 and loan.outstanding_interest == 0:
        loan.status = "closed"
    repayment = SaccoLoanRepayment(organization_id=membership.organization_id,
        loan_id=loan.id, amount=amount, principal_component=principal_component,
        interest_component=interest_component, reference=payload.reference.strip(),
        idempotency_key=payload.idempotency_key, request_hash=request_hash,
        created_by=user.id)
    db.add(repayment)
    db.add(AuditEvent(actor_user_id=user.id, organization_id=membership.organization_id,
        action="sacco.loan.repayment_recorded", resource_type="sacco_loan",
        resource_id=loan.loan_number, detail=f"amount:{amount};principal:{principal_component};interest:{interest_component}"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(SaccoLoanRepayment).filter_by(
            organization_id=membership.organization_id,
            idempotency_key=payload.idempotency_key).first()
        if existing and existing.request_hash == request_hash:
            loan = db.query(SaccoLoan).filter_by(id=loan_id, organization_id=membership.organization_id).first()
            return {"id": existing.id, "loan_id": loan.id, "status": "already_recorded",
                "amount": str(existing.amount), "outstanding_principal": str(loan.outstanding_principal),
                "outstanding_interest": str(loan.outstanding_interest)}
        raise HTTPException(409, "Concurrent repayment conflicts with this idempotency key")
    db.refresh(repayment)
    return {"id": repayment.id, "loan_id": loan.id, "amount": str(repayment.amount),
        "principal_component": str(repayment.principal_component),
        "interest_component": str(repayment.interest_component),
        "outstanding_principal": str(loan.outstanding_principal),
        "outstanding_interest": str(loan.outstanding_interest), "loan_status": loan.status,
        "status": "recorded"}


@router.get("/sacco/loans/{loan_id}/repayments")
def list_sacco_loan_repayments(loan_id: int,
    membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    loan = db.query(SaccoLoan).filter_by(
        id=loan_id, organization_id=membership.organization_id).first()
    if not loan or (loan.branch_id and not can_access_branch(membership, loan.branch_id)):
        raise HTTPException(404, "SACCO loan not found")
    rows = db.query(SaccoLoanRepayment).filter_by(
        organization_id=membership.organization_id, loan_id=loan.id
    ).order_by(SaccoLoanRepayment.created_at, SaccoLoanRepayment.id).all()
    return [{"id": row.id, "amount": str(row.amount),
        "principal_component": str(row.principal_component),
        "interest_component": str(row.interest_component), "reference": row.reference,
        "created_at": row.created_at.isoformat()} for row in rows]


@router.get("/school/learners/{learner_id}/report-card")
def get_school_learner_report_card(learner_id: int, academic_year: int,
    term: str, attendance_start: date | None = None, attendance_end: date | None = None,
    scale_name: str = "default", membership=Depends(active_membership),
    db: Session=Depends(get_db)):
    """Build a report card from published assessments only; drafts never leak."""
    require_permission(membership, "read")
    if academic_year < 2000 or academic_year > 2200 or not term.strip():
        raise HTTPException(422, "A valid academic year and term are required")
    if not re.fullmatch(r"[A-Za-z0-9 _.-]{1,24}", term.strip()):
        raise HTTPException(422, "Invalid term value")
    term = term.strip()
    learner = db.query(SchoolLearner).filter_by(
        id=learner_id, organization_id=membership.organization_id
    ).first()
    if not learner or not can_access_branch(membership, learner.branch_id):
        raise HTTPException(404, "Learner not found")
    class_ids = {learner.class_id} if learner.class_id else set()
    placement_history = db.query(SchoolEnrollmentHistory).filter_by(
        organization_id=membership.organization_id, learner_id=learner.id
    ).all()
    for placement in placement_history:
        class_ids.add(placement.from_class_id)
        class_ids.add(placement.to_class_id)
    class_ids.discard(None)
    historical_classes = db.query(SchoolClass).filter(
        SchoolClass.organization_id == membership.organization_id,
        SchoolClass.id.in_(class_ids),
        SchoolClass.academic_year == academic_year,
    ).order_by(SchoolClass.name, SchoolClass.stream).all() if class_ids else []
    if not historical_classes:
        raise HTTPException(404, "No learner class placement found for the requested academic year")
    if any(not can_access_branch(membership, item.branch_id) for item in historical_classes):
        raise HTTPException(404, "Learner class placement not found")
    report_class_ids = [item.id for item in historical_classes]
    if (attendance_start is None) != (attendance_end is None):
        raise HTTPException(422, "Provide both attendance_start and attendance_end")
    if attendance_start and attendance_end and attendance_start > attendance_end:
        raise HTTPException(422, "Attendance start date must not be after end date")
    assessments = db.query(SchoolAssessment, SchoolSubject.name, SchoolMark.score).join(
        SchoolSubject, and_(SchoolSubject.id == SchoolAssessment.subject_id,
            SchoolSubject.organization_id == membership.organization_id)
    ).outerjoin(SchoolMark, and_(
        SchoolMark.assessment_id == SchoolAssessment.id,
        SchoolMark.learner_id == learner.id,
        SchoolMark.organization_id == membership.organization_id,
    )).filter(
        SchoolAssessment.organization_id == membership.organization_id,
        SchoolAssessment.class_id.in_(report_class_ids),
        SchoolAssessment.academic_year == academic_year,
        SchoolAssessment.term == term,
        SchoolAssessment.status == "published",
        SchoolSubject.is_active.is_(True),
    ).order_by(SchoolSubject.name, SchoolAssessment.created_at).all()
    rows = [{
        "assessment_id": assessment.id, "title": assessment.title,
        "subject_id": assessment.subject_id, "subject_name": subject_name,
        "maximum_score": assessment.maximum_score, "weight": assessment.weight,
        "score": score,
    } for assessment, subject_name, score in assessments]
    grade_bands = db.query(SchoolGradeBand).filter_by(
        organization_id=membership.organization_id, scale_name=scale_name
    ).all()
    try:
        report = build_learner_report_rows(rows, grade_bands)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    attendance = None
    if attendance_start and attendance_end:
        start = datetime.combine(attendance_start, time.min, tzinfo=timezone.utc)
        end = datetime.combine(attendance_end, time.max, tzinfo=timezone.utc)
        records = db.query(SchoolAttendance.status, func.count(SchoolAttendance.id)).filter(
            SchoolAttendance.organization_id == membership.organization_id,
            SchoolAttendance.learner_id == learner.id,
            SchoolAttendance.attendance_date >= start,
            SchoolAttendance.attendance_date <= end,
        ).group_by(SchoolAttendance.status).all()
        counts = {status: count for status, count in records}
        total_days = sum(counts.values())
        attendance = {"start_date": attendance_start.isoformat(),
            "end_date": attendance_end.isoformat(), "total_recorded_days": total_days,
            "present": counts.get("present", 0), "late": counts.get("late", 0),
            "absent": counts.get("absent", 0), "excused": counts.get("excused", 0),
            "attendance_rate": (str((Decimal(counts.get("present", 0) + counts.get("late", 0)) /
                Decimal(total_days) * Decimal("100")).quantize(Decimal("0.01")))
                if total_days else None)}
    return {
        "learner": {"id": learner.id, "admission_number": learner.admission_number,
            "name": f"{learner.first_name} {learner.last_name}",
            "guardian_name": learner.guardian_name},
        "class": {"id": historical_classes[0].id if len(historical_classes) == 1 else None,
            "name": " / ".join(f"{item.name} {item.stream}".strip() for item in historical_classes),
            "stream": historical_classes[0].stream if len(historical_classes) == 1 else "Multiple placements",
            "academic_year": academic_year},
        "class_placements": [{"id": item.id, "name": item.name,
            "stream": item.stream, "branch_id": item.branch_id} for item in historical_classes],
        "academic_year": academic_year, "term": term,
        "publication_basis": "Published assessments only",
        **report, "attendance": attendance,
    }
