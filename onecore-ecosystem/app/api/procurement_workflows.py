from datetime import date, datetime, time, timezone, timedelta
from urllib.parse import urljoin

from fastapi import Request
from decimal import Decimal
import hashlib
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db, SessionLocal
from app.core.models import (
    AccountingAccount, AccountingInvoice, AccountingInvoicePayment, AccountingJournalLine,
    AccountingInvoiceLine, AccountingCreditNote, AccountingCreditNoteLine, AccountingProcurementLink,
    AccountingBankStatementLine, ProcurementSupplier, ProcurementPurchaseOrder,
    ProcurementPurchaseOrderLine, ProcurementApprovalRule, ProcurementApprovalAction,
    ProcurementRFQ, ProcurementRFQLine, ProcurementRFQInvitation, ProcurementRFQQuote, ProcurementRFQQuoteLine,
    ProcurementSupplierReturn, ProcurementSupplierReturnLine, ProcurementGoodsReceipt, ProcurementGoodsReceiptLine,
    ProcurementSupplierInvoice, ProcurementSupplierInvoiceLine,
    ProcurementSupplierInvoice, ProcurementSupplierInvoiceLine, Record, Membership, User,
)
from app.core.procurement_workflow_models import (
    ProcurementSettlement, ProcurementSettlementAllocation, ProcurementApprovalDelegation,
    ProcurementSupplierPortalToken, ProcurementInvoiceDiscrepancy,
    ProcurementSupplierStatement, ProcurementSupplierStatementLine,
)
from app.core.security import current_user
from app.core.config import settings
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, branch_scope_ids, can_access_branch
from app.api.routes import _accounting_make_journal, _accounting_assert_period_open, audit

router = APIRouter(prefix="/api/v1/procurement", tags=["procurement-settlement-and-governance"])
CENT = Decimal("0.01")


class SettlementAllocationIn(BaseModel):
    invoice_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0, multiple_of=CENT, le=Decimal("9999999999999999"))


class SettlementCreateIn(BaseModel):
    supplier_id: int = Field(gt=0)
    payment_account_id: int = Field(gt=0)
    payment_date: date
    provider: str = Field(default="manual", pattern=r"^(manual|bank_transfer|mpesa)$")
    provider_reference: str = Field(default="", max_length=120)
    provider_phone_number: str = Field(default="", max_length=20)
    reference: str = Field(min_length=2, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=100)
    allocations: list[SettlementAllocationIn] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_invoices(self):
        ids = [x.invoice_id for x in self.allocations]
        if len(ids) != len(set(ids)):
            raise ValueError("Each AP invoice may be allocated once per settlement")
        return self


class SettlementVerifyIn(BaseModel):
    provider_reference: str = Field(min_length=2, max_length=120)
    verification_note: str = Field(default="", max_length=500)


class DelegationIn(BaseModel):
    branch_id: str | None = Field(default=None, max_length=36)
    principal_user_id: int = Field(gt=0)
    delegate_user_id: int = Field(gt=0)
    starts_at: datetime
    ends_at: datetime
    reason: str = Field(min_length=5, max_length=500)


class PortalTokenIn(BaseModel):
    supplier_id: int = Field(gt=0)
    expires_at: datetime


class SupplierStatementLineIn(BaseModel):
    transaction_date: date
    description: str = Field(min_length=1, max_length=240)
    reference: str = Field(default="", max_length=120)
    amount: Decimal = Field(ne=0, multiple_of=CENT, le=Decimal("9999999999999999"), ge=Decimal("-9999999999999999"))


class SupplierStatementIn(BaseModel):
    supplier_id: int = Field(gt=0)
    statement_reference: str = Field(min_length=2, max_length=80)
    start_date: date
    end_date: date
    opening_balance: Decimal
    closing_balance: Decimal
    lines: list[SupplierStatementLineIn] = Field(min_length=0, max_length=5000)


class StatementMatchIn(BaseModel):
    invoice_id: int | None = Field(default=None, gt=0)
    payment_id: int | None = Field(default=None, gt=0)
    credit_note_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def one_target(self):
        if sum(bool(x) for x in (self.invoice_id, self.payment_id, self.credit_note_id)) != 1:
            raise ValueError("Choose exactly one invoice, payment or credit note")
        return self


class DiscrepancyIn(BaseModel):
    code: str = Field(pattern=r"^(price|quantity|tax|currency|duplicate|receipt|other)$")
    details: dict = Field(default_factory=dict)


class DiscrepancyResolveIn(BaseModel):
    resolution_note: str = Field(min_length=5, max_length=500)


class SupplierReturnCreditNoteIn(BaseModel):
    accounting_invoice_id: int = Field(gt=0)
    credit_note_number: str = Field(min_length=2, max_length=60, pattern=r"^[A-Za-z0-9._/-]+$")
    issue_date: date
    reason: str = Field(min_length=5, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=100)


def _visible_invoice(db, membership, invoice_id, lock=False):
    q = db.query(AccountingInvoice).filter_by(
        id=invoice_id, organization_id=membership.organization_id, invoice_type="payable"
    )
    if lock:
        q = q.with_for_update()
    row = q.first()
    if not row or (row.branch_id and not can_access_branch(membership, row.branch_id)):
        raise HTTPException(404, "Supplier payable invoice not found")
    return row


def _settlement_response(row):
    return {
        "id": row.id, "supplier_id": row.supplier_id, "amount": str(row.amount),
        "currency": row.currency, "provider": row.provider, "provider_reference": row.provider_reference,
        "provider_phone": ("••••" + row.provider_phone_number[-4:]) if row.provider_phone_number else "",
        "reference": row.reference, "status": row.status, "journal_id": row.journal_id,
        "payment_date": row.payment_date.date().isoformat(),
    }


@router.post("/supplier-settlements", status_code=201)
def create_supplier_settlement(payload: SettlementCreateIn, membership=Depends(active_membership),
                               user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Create an idempotent settlement instruction; money is not marked paid until independently verified."""
    require_permission(membership, "manage")
    existing = db.query(ProcurementSettlement).filter_by(
        organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
    ).first()
    if existing:
        same = (existing.supplier_id == payload.supplier_id
                and existing.payment_account_id == payload.payment_account_id
                and existing.reference == payload.reference.strip()
                and existing.amount == sum((x.amount for x in payload.allocations), Decimal("0.00")))
        if not same:
            raise HTTPException(409, "Settlement idempotency key was used for different payment data")
        return {**_settlement_response(existing), "status": "already_exists"}
    supplier = db.query(ProcurementSupplier).filter_by(
        id=payload.supplier_id, organization_id=membership.organization_id, is_active=True
    ).first()
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    cash = db.query(AccountingAccount).filter_by(
        id=payload.payment_account_id, organization_id=membership.organization_id, is_active=True
    ).first()
    if not cash or cash.account_type != "asset":
        raise HTTPException(422, "Settlement account must be an active cash/bank asset account")
    invoice_ids = sorted(x.invoice_id for x in payload.allocations)
    invoices = db.query(AccountingInvoice).filter(
        AccountingInvoice.organization_id == membership.organization_id,
        AccountingInvoice.id.in_(invoice_ids),
    ).order_by(AccountingInvoice.id).with_for_update().all()
    by_id = {x.id: x for x in invoices}
    if set(by_id) != set(invoice_ids):
        raise HTTPException(404, "One or more supplier invoices were not found")
    currency = None
    branch_ids = set()
    total = Decimal("0.00")
    for item in payload.allocations:
        invoice = by_id[item.invoice_id]
        if invoice.invoice_type != "payable" or invoice.supplier_id != supplier.id:
            raise HTTPException(422, "Every allocation must target a payable invoice for this supplier")
        if invoice.status not in {"posted", "partially_paid"}:
            raise HTTPException(409, "Only posted and partially paid AP invoices can be settled")
        if invoice.branch_id and not can_access_branch(membership, invoice.branch_id):
            raise HTTPException(404, "Supplier invoice not found")
        branch_ids.add(invoice.branch_id)
        balance = Decimal(invoice.total) - Decimal(invoice.amount_paid)
        if item.amount > balance:
            raise HTTPException(422, f"Allocation exceeds invoice {invoice.invoice_number} outstanding balance")
        if currency is None:
            currency = invoice.currency
        elif currency != invoice.currency:
            raise HTTPException(422, "A settlement cannot combine invoices in different currencies")
        total += item.amount
    if len(branch_ids) > 1:
        raise HTTPException(422, "A settlement batch cannot span multiple branches")
    if currency != cash_currency(db, membership.organization_id):
        # The ledger is single-base-currency; foreign-currency payments require a configured FX workflow.
        raise HTTPException(422, "Settlement currency must equal the organization's accounting base currency")
    callback_token = ""
    provider_phone = ""
    if payload.provider == "mpesa":
        if currency != "KES" or total != total.quantize(Decimal("1")):
            raise HTTPException(422, "M-Pesa B2C supplier payouts require whole KES amounts")
        if not payload.provider_phone_number:
            raise HTTPException(422, "A supplier M-Pesa phone number is required for B2C settlement")
        from app.api.mpesa import _enabled, normalize_phone
        _enabled()
        if not all((settings.mpesa_initiator_name, settings.mpesa_security_credential,
                    settings.mpesa_b2c_result_url, settings.mpesa_b2c_timeout_url)):
            raise HTTPException(503, "M-Pesa B2C initiator, encrypted credential and callback URLs are required")
        if not settings.mpesa_b2c_result_url.startswith("https://") or not settings.mpesa_b2c_timeout_url.startswith("https://"):
            raise HTTPException(503, "M-Pesa B2C result and timeout URLs must use public HTTPS")
        try:
            provider_phone = normalize_phone(payload.provider_phone_number)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        callback_token = secrets.token_urlsafe(32)
    row = ProcurementSettlement(
        organization_id=membership.organization_id, supplier_id=supplier.id,
        payment_account_id=cash.id, amount=total, currency=currency,
        provider=payload.provider, provider_reference=payload.provider_reference.strip(),
        provider_phone_number=provider_phone,
        callback_token_hash=hashlib.sha256(callback_token.encode()).hexdigest() if callback_token else "",
        reference=payload.reference.strip(),
        status="pending_provider" if payload.provider == "mpesa" else "pending_verification",
        payment_date=datetime.combine(payload.payment_date, time.min, tzinfo=timezone.utc),
        idempotency_key=payload.idempotency_key, created_by=user.id,
    )
    db.add(row)
    db.flush()
    for item in payload.allocations:
        db.add(ProcurementSettlementAllocation(
            organization_id=membership.organization_id, settlement_id=row.id,
            invoice_id=item.invoice_id, amount=item.amount,
        ))
    audit(db, user.id, membership.organization_id, "procurement.settlement.initiated",
          "procurement_settlement", row.id, f"{row.amount}:{row.provider}:{row.reference}")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Settlement conflicts with another request")
    db.refresh(row)
    if row.provider == "mpesa":
        from app.api.mpesa import _post
        try:
            response = _post("mpesa/b2c/v1/paymentrequest", {
                "InitiatorName": settings.mpesa_initiator_name,
                "SecurityCredential": settings.mpesa_security_credential,
                "CommandID": "BusinessPayment", "Amount": int(total),
                "PartyA": settings.mpesa_shortcode, "PartyB": provider_phone,
                "Remarks": f"OneCore supplier settlement {row.id}"[:100],
                "QueueTimeOutURL": urljoin(settings.mpesa_b2c_timeout_url.rstrip("/") + "/", callback_token),
                "ResultURL": urljoin(settings.mpesa_b2c_result_url.rstrip("/") + "/", callback_token),
                "Occasion": f"SUP-{row.id}"[:20],
            })
            if response.get("ResponseCode") == "0":
                row.provider_conversation_id = str(response.get("ConversationID") or "")[:100]
                row.provider_originator_id = str(response.get("OriginatorConversationID") or "")[:100]
                if not row.provider_conversation_id or not row.provider_originator_id:
                    row.status = "unknown"
                    row.provider_result_description = "Daraja accepted request without correlation IDs; reconcile before retrying"
            else:
                row.status = "failed"
                row.provider_result_description = str(response.get("ResponseDescription") or response.get("errorMessage") or "Daraja rejected B2C request")[:500]
        except HTTPException as exc:
            row.status = "unknown" if exc.status_code == 503 else "failed"
            row.provider_result_description = str(exc.detail)[:500]
        db.commit()
        db.refresh(row)
    return _settlement_response(row)


def cash_currency(db, organization_id):
    from app.core.models import Organization
    org = db.query(Organization).filter_by(id=organization_id, is_active=True).first()
    return org.currency if org else None


@router.post("/supplier-settlements/{settlement_id}/verify")
def verify_supplier_settlement(settlement_id: int, payload: SettlementVerifyIn,
                               membership=Depends(active_membership), user: User = Depends(current_user),
                               db: Session = Depends(get_db)):
    """Verify a bank/provider-confirmed payment and atomically post AP allocations and cash journal."""
    require_permission(membership, "manage")
    settlement = db.query(ProcurementSettlement).filter_by(
        id=settlement_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not settlement:
        raise HTTPException(404, "Settlement not found")
    if settlement.status == "settled":
        if settlement.provider_reference != payload.provider_reference.strip():
            raise HTTPException(409, "Settlement is already verified against a different provider reference")
        return {**_settlement_response(settlement), "status": "already_settled"}
    if settlement.provider == "mpesa":
        if settlement.status != "provider_confirmed" or settlement.provider_reference != payload.provider_reference.strip():
            raise HTTPException(409, "M-Pesa settlement must have a verified successful B2C callback before posting")
    elif settlement.status != "pending_verification":
        raise HTTPException(409, "Only pending settlements can be verified")
    allocations = db.query(ProcurementSettlementAllocation).filter_by(
        organization_id=membership.organization_id, settlement_id=settlement.id
    ).order_by(ProcurementSettlementAllocation.invoice_id).all()
    if not allocations or sum((Decimal(x.amount) for x in allocations), Decimal("0.00")) != Decimal(settlement.amount):
        raise HTTPException(409, "Settlement allocation total does not reconcile to payment amount")
    invoice_ids = sorted(x.invoice_id for x in allocations)
    invoices = db.query(AccountingInvoice).filter(
        AccountingInvoice.organization_id == membership.organization_id,
        AccountingInvoice.id.in_(invoice_ids),
    ).order_by(AccountingInvoice.id).with_for_update().all()
    by_id = {x.id: x for x in invoices}
    if set(by_id) != set(invoice_ids):
        raise HTTPException(409, "An allocated AP invoice is no longer available")
    cash = db.query(AccountingAccount).filter_by(
        id=settlement.payment_account_id, organization_id=membership.organization_id, is_active=True
    ).first()
    if not cash or cash.account_type != "asset":
        raise HTTPException(409, "Settlement cash/bank account is no longer active")
    _accounting_assert_period_open(db, membership.organization_id, settlement.payment_date.date())
    lines = []
    for allocation in allocations:
        invoice = by_id[allocation.invoice_id]
        if invoice.invoice_type != "payable" or invoice.supplier_id != settlement.supplier_id:
            raise HTTPException(409, "Settlement allocation no longer matches supplier payable")
        if invoice.status not in {"posted", "partially_paid"}:
            raise HTTPException(409, "Allocated invoice is not in a payable settlement state")
        amount = Decimal(allocation.amount)
        if amount > Decimal(invoice.total) - Decimal(invoice.amount_paid):
            raise HTTPException(409, "Invoice balance changed after settlement instruction")
        lines.append({"account_id": invoice.control_account_id,
                      "description": "Settle supplier invoice " + invoice.invoice_number,
                      "debit": amount, "credit": Decimal("0.00")})
    lines.append({"account_id": cash.id, "description": "Supplier payment " + settlement.reference,
                  "debit": Decimal("0.00"), "credit": Decimal(settlement.amount)})
    journal = _accounting_make_journal(
        db, membership, user, settlement.payment_date.date(), payload.provider_reference.strip(),
        "Supplier settlement " + settlement.reference, lines,
        invoices[0].branch_id,
    )
    for allocation in allocations:
        invoice = by_id[allocation.invoice_id]
        amount = Decimal(allocation.amount)
        payment = AccountingInvoicePayment(
            organization_id=membership.organization_id, invoice_id=invoice.id,
            payment_account_id=cash.id, journal_id=journal.id, amount=amount,
            payment_date=settlement.payment_date, reference=payload.provider_reference.strip(),
            idempotency_key=f"proc-settlement-{settlement.id}-{invoice.id}", created_by=user.id,
        )
        db.add(payment)
        db.flush()
        allocation.accounting_payment_id = payment.id
        invoice.amount_paid = Decimal(invoice.amount_paid) + amount
        invoice.status = "paid" if invoice.amount_paid == invoice.total else "partially_paid"
    if settlement.provider != "mpesa":
        settlement.provider_reference = payload.provider_reference.strip()
    settlement.status = "settled"
    settlement.journal_id = journal.id
    settlement.verified_by = user.id
    settlement.verified_at = datetime.now(timezone.utc)
    audit(db, user.id, membership.organization_id, "procurement.settlement.verified",
          "procurement_settlement", settlement.id, payload.verification_note.strip())
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Settlement verification conflicted with another request")
    return {**_settlement_response(settlement), "status": "settled",
            "journal_id": journal.id, "allocation_count": len(allocations)}




def _supplier_b2c_callback(db: Session, token: str, body: dict, timeout: bool = False):
    digest = hashlib.sha256(token.encode()).hexdigest()
    settlement = db.query(ProcurementSettlement).filter_by(
        callback_token_hash=digest, provider="mpesa"
    ).with_for_update().first()
    if not settlement:
        return False
    if settlement.status in {"settled", "provider_confirmed"}:
        return True
    result = body.get("Result") or body
    conversation = str(result.get("ConversationID") or "")
    if not conversation:
        return False
    if not settlement.provider_conversation_id and settlement.status in {"pending_provider", "unknown"}:
        settlement.provider_conversation_id = conversation[:100]
        settlement.provider_originator_id = str(result.get("OriginatorConversationID") or "")[:100]
    elif conversation != settlement.provider_conversation_id:
        return False
    settlement.provider_result_code = str(result.get("ResultCode") if result.get("ResultCode") is not None else "")[:40]
    settlement.provider_result_description = str(result.get("ResultDesc") or ("Provider timeout" if timeout else ""))[:500]
    if timeout:
        settlement.status = "unknown"
    elif settlement.provider_result_code == "0":
        params = ((result.get("ResultParameters") or {}).get("ResultParameter") or [])
        metadata = {str(x.get("Key")): x.get("Value") for x in params if isinstance(x, dict)}
        try:
            paid = Decimal(str(metadata.get("TransactionAmount"))).quantize(CENT)
        except Exception:
            settlement.status = "exception"
            settlement.provider_result_description = "Successful B2C callback is missing a valid transaction amount"
            db.commit()
            return True
        receipt = str(metadata.get("TransactionReceipt") or "").strip()
        if paid != Decimal(settlement.amount).quantize(CENT) or not receipt:
            settlement.status = "exception"
            settlement.provider_result_description = "B2C callback amount or receipt does not match the settlement"
            db.commit()
            return True
        duplicate = db.query(ProcurementSettlement).filter(
            ProcurementSettlement.organization_id == settlement.organization_id,
            ProcurementSettlement.provider_reference == receipt,
            ProcurementSettlement.id != settlement.id,
        ).first()
        if duplicate:
            settlement.status = "exception"
            settlement.provider_result_description = "M-Pesa receipt has already been used by another supplier settlement"
            db.commit()
            return True
        settlement.provider_reference = receipt[:120]
        settlement.status = "provider_confirmed"
    else:
        settlement.status = "failed"
    db.commit()
    return True


@router.post("/supplier-settlements/callbacks/b2c/result/{token}")
async def supplier_b2c_result_callback(token: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid M-Pesa B2C callback JSON")
    db = SessionLocal()
    try:
        if not _supplier_b2c_callback(db, token, body):
            raise HTTPException(404, "Unknown or mismatched supplier B2C callback")
        return {"ResultCode": 0, "ResultDesc": "Accepted"}
    finally:
        db.close()


@router.post("/supplier-settlements/callbacks/b2c/timeout/{token}")
async def supplier_b2c_timeout_callback(token: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid M-Pesa B2C timeout JSON")
    db = SessionLocal()
    try:
        if not _supplier_b2c_callback(db, token, body, timeout=True):
            raise HTTPException(404, "Unknown or mismatched supplier B2C timeout")
        return {"ResultCode": 0, "ResultDesc": "Accepted"}
    finally:
        db.close()

@router.get("/supplier-settlements")
def list_supplier_settlements(supplier_id: int | None = Query(default=None, gt=0),
                              membership=Depends(active_membership), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    q = db.query(ProcurementSettlement).filter_by(organization_id=membership.organization_id)
    if supplier_id:
        q = q.filter(ProcurementSettlement.supplier_id == supplier_id)
    rows = q.order_by(ProcurementSettlement.id.desc()).limit(500).all()
    return [_settlement_response(x) for x in rows]


@router.get("/supplier-settlements/{settlement_id}/remittance")
def supplier_remittance_advice(settlement_id: int, membership=Depends(active_membership),
                                db: Session = Depends(get_db)):
    require_permission(membership, "read")
    row = db.query(ProcurementSettlement).filter_by(
        id=settlement_id, organization_id=membership.organization_id, status="settled"
    ).first()
    if not row:
        raise HTTPException(404, "Verified supplier settlement not found")
    supplier = db.query(ProcurementSupplier).filter_by(
        id=row.supplier_id, organization_id=membership.organization_id
    ).first()
    allocations = db.query(ProcurementSettlementAllocation, AccountingInvoice).join(
        AccountingInvoice, AccountingInvoice.id == ProcurementSettlementAllocation.invoice_id
    ).filter(ProcurementSettlementAllocation.settlement_id == row.id,
              ProcurementSettlementAllocation.organization_id == membership.organization_id).all()
    return {
        "remittance_number": f"REM-{row.id:08d}", "supplier": supplier.name if supplier else "",
        "supplier_id": row.supplier_id, "payment_date": row.payment_date.date().isoformat(),
        "provider": row.provider, "provider_reference": row.provider_reference,
        "payment_reference": row.reference, "currency": row.currency, "total_paid": str(row.amount),
        "journal_id": row.journal_id,
        "allocations": [{"invoice_id": invoice.id, "invoice_number": invoice.invoice_number,
                         "amount": str(allocation.amount), "balance_after_payment": str(Decimal(invoice.total)-Decimal(invoice.amount_paid))}
                        for allocation, invoice in allocations],
        "status": "verified",
    }


@router.post("/approval-delegations", status_code=201)
def create_approval_delegation(payload: DelegationIn, membership=Depends(active_membership),
                               user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    now = datetime.now(timezone.utc)
    starts = payload.starts_at if payload.starts_at.tzinfo else payload.starts_at.replace(tzinfo=timezone.utc)
    ends = payload.ends_at if payload.ends_at.tzinfo else payload.ends_at.replace(tzinfo=timezone.utc)
    if payload.principal_user_id == payload.delegate_user_id or starts >= ends or ends <= now:
        raise HTTPException(422, "Delegation users and validity window are invalid")
    if payload.branch_id and not can_access_branch(membership, payload.branch_id):
        raise HTTPException(404, "Branch not found")
    members = db.query(Membership).filter(
        Membership.organization_id == membership.organization_id, Membership.is_active == True,
        Membership.user_id.in_([payload.principal_user_id, payload.delegate_user_id])
    ).all()
    if {x.user_id for x in members} != {payload.principal_user_id, payload.delegate_user_id}:
        raise HTTPException(422, "Principal and delegate must be active organization members")
    overlap = db.query(ProcurementApprovalDelegation).filter(
        ProcurementApprovalDelegation.organization_id == membership.organization_id,
        ProcurementApprovalDelegation.principal_user_id == payload.principal_user_id,
        ProcurementApprovalDelegation.revoked_at.is_(None),
        ProcurementApprovalDelegation.starts_at < ends,
        ProcurementApprovalDelegation.ends_at > starts,
    ).first()
    if overlap:
        raise HTTPException(409, "Principal already has an overlapping active delegation")
    row = ProcurementApprovalDelegation(
        organization_id=membership.organization_id, branch_id=payload.branch_id,
        principal_user_id=payload.principal_user_id, delegate_user_id=payload.delegate_user_id,
        starts_at=starts, ends_at=ends, reason=payload.reason.strip(), created_by=user.id,
    )
    db.add(row)
    db.commit()
    audit(db, user.id, membership.organization_id, "procurement.approval.delegation.created",
          "procurement_approval_delegation", row.id, row.reason)
    return {"id": row.id, "principal_user_id": row.principal_user_id,
            "delegate_user_id": row.delegate_user_id, "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(), "status": "active"}


@router.get("/approval-delegations")
def list_approval_delegations(membership=Depends(active_membership), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    rows = db.query(ProcurementApprovalDelegation).filter_by(
        organization_id=membership.organization_id
    ).order_by(ProcurementApprovalDelegation.id.desc()).limit(300).all()
    return [{"id": x.id, "branch_id": x.branch_id, "principal_user_id": x.principal_user_id,
             "delegate_user_id": x.delegate_user_id, "starts_at": x.starts_at.isoformat(),
             "ends_at": x.ends_at.isoformat(), "reason": x.reason,
             "revoked_at": x.revoked_at.isoformat() if x.revoked_at else None} for x in rows]


@router.post("/approval-delegations/{delegation_id}/revoke")
def revoke_approval_delegation(delegation_id: int, membership=Depends(active_membership),
                               user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(ProcurementApprovalDelegation).filter_by(
        id=delegation_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not row:
        raise HTTPException(404, "Delegation not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
        audit(db, user.id, membership.organization_id, "procurement.approval.delegation.revoked",
              "procurement_approval_delegation", row.id)
    return {"id": row.id, "status": "revoked"}


@router.post("/orders/{order_id}/approve-as-delegate")
def approve_purchase_order_as_delegate(order_id: int, delegation_id: int,
                                       membership=Depends(active_membership),
                                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "create")
    order = db.query(ProcurementPurchaseOrder).filter_by(
        id=order_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not order or (order.branch_id and not can_access_branch(membership, order.branch_id)):
        raise HTTPException(404, "Purchase order not found")
    if order.status != "draft" or order.created_by == user.id:
        raise HTTPException(409, "Order is not awaiting approval or creator cannot approve")
    delegation = db.query(ProcurementApprovalDelegation).filter_by(
        id=delegation_id, organization_id=membership.organization_id,
        delegate_user_id=user.id, revoked_at=None,
    ).with_for_update().first()
    now = datetime.now(timezone.utc)
    if not delegation or not (delegation.starts_at <= now <= delegation.ends_at):
        raise HTTPException(403, "No active delegation authorizes this approval")
    if delegation.branch_id and delegation.branch_id != order.branch_id:
        raise HTTPException(403, "Delegation does not cover this purchase-order branch")
    principal_membership = db.query(Membership).filter_by(
        organization_id=membership.organization_id, user_id=delegation.principal_user_id, is_active=True
    ).first()
    if not principal_membership:
        raise HTTPException(403, "Delegating approver is no longer an active member")
    lines = db.query(ProcurementPurchaseOrderLine).filter_by(
        organization_id=membership.organization_id, purchase_order_id=order.id
    ).all()
    amount = sum((Decimal(x.quantity_ordered) * Decimal(x.unit_cost) for x in lines), Decimal("0.00"))
    rules = db.query(ProcurementApprovalRule).filter(
        ProcurementApprovalRule.organization_id == membership.organization_id,
        ProcurementApprovalRule.is_active == True,
        ProcurementApprovalRule.minimum_amount <= amount,
    ).order_by(ProcurementApprovalRule.approval_level).all()
    rules = [x for x in rules if x.maximum_amount is None or amount <= x.maximum_amount]
    if not rules:
        raise HTTPException(409, "No approval policy applies to this purchase order")
    if delegation.principal_user_id == order.created_by:
        raise HTTPException(403, "The purchase-order creator cannot delegate approval of their own order")
    actions = db.query(ProcurementApprovalAction).filter_by(
        organization_id=membership.organization_id, entity_type="purchase_order", entity_id=order.id
    ).all()
    action_levels = {x.approval_level for x in actions if x.action == "approved"}
    next_rule = next((x for x in rules if x.approval_level not in action_levels), None)
    if not next_rule or next_rule.approval_level != rules[0].approval_level:
        # A later level may be delegated only after all earlier levels have approved.
        next_rule = next((x for x in rules if x.approval_level not in action_levels), None)
    if not next_rule or next_rule.approver_role != principal_membership.role:
        raise HTTPException(403, "Delegation principal is not eligible for the current approval level")
    if db.query(ProcurementApprovalAction).filter_by(
        organization_id=membership.organization_id, entity_type="purchase_order",
        entity_id=order.id, approval_level=next_rule.approval_level
    ).first():
        raise HTTPException(409, "This approval level has already been decided")
    db.add(ProcurementApprovalAction(
        organization_id=membership.organization_id, entity_type="purchase_order",
        entity_id=order.id, approval_level=next_rule.approval_level,
        approver_user_id=user.id, action="approved", note=f"Delegated for user {delegation.principal_user_id}",
    ))
    approved_levels = action_levels | {next_rule.approval_level}
    if all(rule.approval_level in approved_levels for rule in rules):
        order.status = "approved"
        order.approved_by = user.id
        order.approved_at = now
    db.commit()
    audit(db, user.id, membership.organization_id, "procurement.purchase_order.delegated_approval",
          "purchase_order", order.id, f"delegation:{delegation.id};level:{next_rule.approval_level}")
    return {"id": order.id, "status": order.status, "approved_level": next_rule.approval_level,
            "remaining_levels": [x.approval_level for x in rules if x.approval_level not in approved_levels]}




class SupplierPortalQuoteLineIn(BaseModel):
    rfq_line_id: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0, multiple_of=CENT, le=Decimal("9999999999999999"))
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)


class SupplierPortalQuoteIn(BaseModel):
    currency: str = Field(default="KES", pattern=r"^[A-Z]{3}$")
    delivery_days: int = Field(ge=0, le=3650)
    lines: list[SupplierPortalQuoteLineIn] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_lines(self):
        ids = [x.rfq_line_id for x in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Each RFQ line must be quoted exactly once")
        return self


@router.get("/supplier-portal/rfqs")
def supplier_portal_rfqs(token: str = Header(default="", alias="X-Supplier-Portal-Token"),
                          db: Session = Depends(get_db)):
    access, supplier = _portal_supplier(token, db)
    invitations = db.query(ProcurementRFQInvitation).filter_by(
        organization_id=access.organization_id, supplier_id=supplier.id
    ).all()
    result = []
    for invite in invitations:
        rfq = db.query(ProcurementRFQ).filter_by(
            id=invite.rfq_id, organization_id=access.organization_id, status="open"
        ).first()
        if not rfq:
            continue
        lines = db.query(ProcurementRFQLine).filter_by(
            rfq_id=rfq.id, organization_id=access.organization_id
        ).order_by(ProcurementRFQLine.id).all()
        result.append({"id": rfq.id, "rfq_number": rfq.rfq_number,
                       "closing_date": rfq.closing_date.isoformat(),
                       "status": invite.status,
                       "lines": [{"id": x.id, "product_id": x.product_id, "quantity": str(x.quantity)} for x in lines]})
    return result


@router.post("/supplier-portal/rfqs/{rfq_id}/quotes", status_code=201)
def supplier_portal_submit_quote(rfq_id: int, payload: SupplierPortalQuoteIn,
                                 token: str = Header(default="", alias="X-Supplier-Portal-Token"),
                                 db: Session = Depends(get_db)):
    access, supplier = _portal_supplier(token, db)
    rfq = db.query(ProcurementRFQ).filter_by(
        id=rfq_id, organization_id=access.organization_id, status="open"
    ).with_for_update().first()
    if not rfq or rfq.closing_date.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(404, "Open RFQ not found")
    invitation = db.query(ProcurementRFQInvitation).filter_by(
        organization_id=access.organization_id, rfq_id=rfq.id, supplier_id=supplier.id
    ).first()
    if not invitation:
        raise HTTPException(403, "Supplier was not invited to this RFQ")
    if db.query(ProcurementRFQQuote).filter_by(
        organization_id=access.organization_id, rfq_id=rfq.id, supplier_id=supplier.id
    ).first():
        raise HTTPException(409, "Supplier has already submitted a quotation")
    rfq_lines = db.query(ProcurementRFQLine).filter_by(
        organization_id=access.organization_id, rfq_id=rfq.id
    ).all()
    if {x.rfq_line_id for x in payload.lines} != {x.id for x in rfq_lines}:
        raise HTTPException(422, "Quotation must price every RFQ line exactly once")
    quote = ProcurementRFQQuote(
        organization_id=access.organization_id, rfq_id=rfq.id, supplier_id=supplier.id,
        currency=payload.currency, delivery_days=payload.delivery_days, status="submitted",
        submitted_by=access.created_by,
    )
    db.add(quote)
    db.flush()
    for item in payload.lines:
        db.add(ProcurementRFQQuoteLine(
            organization_id=access.organization_id, quote_id=quote.id,
            rfq_line_id=item.rfq_line_id, unit_price=item.unit_price, tax_rate=item.tax_rate,
        ))
    invitation.status = "quoted"
    db.commit()
    return {"id": quote.id, "rfq_id": rfq.id, "status": "submitted"}


@router.get("/supplier-portal/purchase-orders/{order_id}")
def supplier_portal_purchase_order_detail(order_id: int,
        token: str = Header(default="", alias="X-Supplier-Portal-Token"), db: Session = Depends(get_db)):
    access, supplier = _portal_supplier(token, db)
    order = db.query(ProcurementPurchaseOrder).filter_by(
        id=order_id, organization_id=access.organization_id, supplier_id=supplier.id
    ).first()
    if not order:
        raise HTTPException(404, "Purchase order not found")
    lines = db.query(ProcurementPurchaseOrderLine).filter_by(
        organization_id=access.organization_id, purchase_order_id=order.id
    ).all()
    return {"id": order.id, "order_number": order.order_number, "status": order.status,
            "currency": order.currency, "notes": order.notes,
            "lines": [{"id": x.id, "product_id": x.product_id, "quantity_ordered": str(x.quantity_ordered),
                       "quantity_received": str(x.quantity_received), "unit_cost": str(x.unit_cost)} for x in lines]}


@router.post("/supplier-portal/tokens/{token_id}/revoke")
def revoke_supplier_portal_token(token_id: int, membership=Depends(active_membership),
                                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(ProcurementSupplierPortalToken).filter_by(
        id=token_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not row:
        raise HTTPException(404, "Supplier portal token not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
        audit(db, user.id, membership.organization_id, "procurement.supplier_portal.token_revoked",
              "supplier_portal_token", row.id)
    return {"id": row.id, "status": "revoked"}

@router.post("/supplier-portal/tokens", status_code=201)
def create_supplier_portal_token(payload: PortalTokenIn, membership=Depends(active_membership),
                                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    supplier = db.query(ProcurementSupplier).filter_by(
        id=payload.supplier_id, organization_id=membership.organization_id, is_active=True
    ).first()
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    expires = payload.expires_at if payload.expires_at.tzinfo else payload.expires_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if expires <= now or expires > now + timedelta(days=366):
        raise HTTPException(422, "Portal token expiry must be within the next 12 months")
    raw = secrets.token_urlsafe(32)
    row = ProcurementSupplierPortalToken(
        organization_id=membership.organization_id, supplier_id=supplier.id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        scopes={"read_purchase_orders": True, "read_invoices": True, "read_rfqs": True, "delivery_updates": True},
        expires_at=expires, created_by=user.id,
    )
    db.add(row)
    db.commit()
    audit(db, user.id, membership.organization_id, "procurement.supplier_portal.token_created",
          "supplier_portal_token", row.id, f"supplier:{supplier.id};expires:{expires.isoformat()}")
    return {"id": row.id, "supplier_id": supplier.id, "token": raw,
            "expires_at": expires.isoformat(), "warning": "Store this token securely; it cannot be retrieved again."}


def _portal_supplier(token, db):
    if not token or len(token) > 200:
        raise HTTPException(401, "Supplier portal token is required")
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = db.query(ProcurementSupplierPortalToken).filter_by(token_hash=digest).first()
    now = datetime.now(timezone.utc)
    if not row or row.revoked_at or row.expires_at <= now:
        raise HTTPException(401, "Supplier portal token is invalid or expired")
    supplier = db.query(ProcurementSupplier).filter_by(
        id=row.supplier_id, organization_id=row.organization_id, is_active=True
    ).first()
    if not supplier:
        raise HTTPException(401, "Supplier portal access is no longer active")
    return row, supplier


@router.get("/supplier-portal/purchase-orders")
def supplier_portal_purchase_orders(token: str = Header(default="", alias="X-Supplier-Portal-Token"),
                                    db: Session = Depends(get_db)):
    access, supplier = _portal_supplier(token, db)
    rows = db.query(ProcurementPurchaseOrder).filter_by(
        organization_id=access.organization_id, supplier_id=supplier.id
    ).order_by(ProcurementPurchaseOrder.id.desc()).limit(200).all()
    return [{"id": x.id, "order_number": x.order_number, "status": x.status,
             "currency": x.currency, "created_at": x.created_at.isoformat()} for x in rows]


@router.get("/supplier-portal/invoices")
def supplier_portal_invoices(token: str = Header(default="", alias="X-Supplier-Portal-Token"),
                              db: Session = Depends(get_db)):
    access, supplier = _portal_supplier(token, db)
    rows = db.query(ProcurementSupplierInvoice).filter_by(
        organization_id=access.organization_id, supplier_id=supplier.id
    ).order_by(ProcurementSupplierInvoice.id.desc()).limit(200).all()
    return [{"id": x.id, "invoice_number": x.invoice_number, "invoice_date": x.invoice_date.date().isoformat(),
             "currency": x.currency, "status": x.status, "subtotal": str(x.subtotal),
             "tax_total": str(x.tax_total), "total": str(Decimal(x.subtotal)+Decimal(x.tax_total))}
            for x in rows]


@router.post("/supplier-portal/delivery-updates", status_code=201)
def supplier_portal_delivery_update(payload: dict,
                                    token: str = Header(default="", alias="X-Supplier-Portal-Token"),
                                    db: Session = Depends(get_db)):
    access, supplier = _portal_supplier(token, db)
    order_id = payload.get("purchase_order_id")
    status = payload.get("status")
    note = str(payload.get("note", "")).strip()
    if not isinstance(order_id, int) or status not in {"dispatched", "in_transit", "delayed", "delivered"} or len(note) > 500:
        raise HTTPException(422, "Valid purchase_order_id, delivery status and note are required")
    order = db.query(ProcurementPurchaseOrder).filter_by(
        id=order_id, organization_id=access.organization_id, supplier_id=supplier.id
    ).first()
    if not order:
        raise HTTPException(404, "Purchase order not found")
    event = Record(organization_id=access.organization_id, module_key="procurement",
        record_type="supplier_delivery_update",
        data={"supplier_id": supplier.id, "purchase_order_id": order.id,
              "status": status, "note": note, "reported_at": datetime.now(timezone.utc).isoformat()},
        branch_id=order.branch_id, created_by=access.created_by)
    db.add(event)
    db.commit()
    return {"id": event.id, "purchase_order_id": order.id, "status": status, "recorded": True}


@router.post("/supplier-statements", status_code=201)
def import_supplier_statement(payload: SupplierStatementIn, membership=Depends(active_membership),
                              user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    supplier = db.query(ProcurementSupplier).filter_by(
        id=payload.supplier_id, organization_id=membership.organization_id
    ).first()
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    if payload.end_date < payload.start_date:
        raise HTTPException(422, "Statement end date cannot precede start date")
    if len(payload.lines) != len({(x.transaction_date, x.reference, x.description) for x in payload.lines}):
        raise HTTPException(422, "Duplicate statement lines are not allowed")
    row = ProcurementSupplierStatement(
        organization_id=membership.organization_id, supplier_id=supplier.id,
        statement_reference=payload.statement_reference.strip(),
        start_date=datetime.combine(payload.start_date, time.min, tzinfo=timezone.utc),
        end_date=datetime.combine(payload.end_date, time.max, tzinfo=timezone.utc),
        opening_balance=payload.opening_balance, closing_balance=payload.closing_balance,
        status="open", created_by=user.id,
    )
    db.add(row)
    db.flush()
    for number, item in enumerate(payload.lines, start=1):
        db.add(ProcurementSupplierStatementLine(
            organization_id=membership.organization_id, statement_id=row.id, line_number=number,
            transaction_date=datetime.combine(item.transaction_date, time.min, tzinfo=timezone.utc),
            description=item.description.strip(), reference=item.reference.strip(), amount=item.amount,
        ))
    db.commit()
    audit(db, user.id, membership.organization_id, "procurement.supplier_statement.imported",
          "supplier_statement", row.id, row.statement_reference)
    return {"id": row.id, "statement_reference": row.statement_reference,
            "line_count": len(payload.lines), "status": row.status}


@router.get("/supplier-statements/{statement_id}")
def get_supplier_statement(statement_id: int, membership=Depends(active_membership),
                           db: Session = Depends(get_db)):
    require_permission(membership, "read")
    row = db.query(ProcurementSupplierStatement).filter_by(
        id=statement_id, organization_id=membership.organization_id
    ).first()
    if not row:
        raise HTTPException(404, "Supplier statement not found")
    lines = db.query(ProcurementSupplierStatementLine).filter_by(
        statement_id=row.id, organization_id=membership.organization_id
    ).order_by(ProcurementSupplierStatementLine.line_number).all()
    return {"id": row.id, "supplier_id": row.supplier_id, "statement_reference": row.statement_reference,
            "opening_balance": str(row.opening_balance), "closing_balance": str(row.closing_balance),
            "status": row.status,
            "lines": [{"id": x.id, "line_number": x.line_number, "date": x.transaction_date.date().isoformat(),
                       "description": x.description, "reference": x.reference, "amount": str(x.amount),
                       "matched_invoice_id": x.matched_invoice_id, "matched_payment_id": x.matched_payment_id,
                       "matched_credit_note_id": x.matched_credit_note_id}
                      for x in lines]}


@router.post("/supplier-statements/{statement_id}/lines/{line_id}/match")
def match_supplier_statement_line(statement_id: int, line_id: int, payload: StatementMatchIn,
                                  membership=Depends(active_membership), user: User = Depends(current_user),
                                  db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    statement = db.query(ProcurementSupplierStatement).filter_by(
        id=statement_id, organization_id=membership.organization_id, status="open"
    ).with_for_update().first()
    line = db.query(ProcurementSupplierStatementLine).filter_by(
        id=line_id, statement_id=statement_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not statement or not line:
        raise HTTPException(404, "Open supplier statement line not found")
    if line.matched_invoice_id or line.matched_payment_id or line.matched_credit_note_id:
        raise HTTPException(409, "Statement line is already matched")
    if payload.invoice_id:
        target = db.query(AccountingInvoice).filter_by(
            id=payload.invoice_id, organization_id=membership.organization_id,
            supplier_id=statement.supplier_id, invoice_type="payable",
        ).first()
        if not target or Decimal(target.total) != abs(Decimal(line.amount)):
            raise HTTPException(422, "Invoice supplier or statement amount does not match")
        line.matched_invoice_id = target.id
    else:
        target = db.query(AccountingInvoicePayment).join(
            AccountingInvoice, AccountingInvoice.id == AccountingInvoicePayment.invoice_id
        ).filter(AccountingInvoicePayment.id == payload.payment_id,
                 AccountingInvoicePayment.organization_id == membership.organization_id,
                 AccountingInvoice.supplier_id == statement.supplier_id).first()
        if not target or Decimal(target.amount) != abs(Decimal(line.amount)):
            raise HTTPException(422, "Payment supplier or statement amount does not match")
        line.matched_payment_id = target.id
    if payload.credit_note_id:
        target = db.query(AccountingCreditNote).join(
            AccountingInvoice, AccountingInvoice.id == AccountingCreditNote.invoice_id
        ).filter(AccountingCreditNote.id == payload.credit_note_id,
                 AccountingCreditNote.organization_id == membership.organization_id,
                 AccountingCreditNote.status == "posted",
                 AccountingInvoice.supplier_id == statement.supplier_id).first()
        if not target or Decimal(target.total) != abs(Decimal(line.amount)):
            raise HTTPException(422, "Credit note supplier or statement amount does not match")
        line.matched_credit_note_id = target.id
    line.matched_by = user.id
    line.matched_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": line.id, "status": "matched"}


@router.post("/supplier-statements/{statement_id}/reconcile")
def reconcile_supplier_statement(statement_id: int, membership=Depends(active_membership),
                                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(ProcurementSupplierStatement).filter_by(
        id=statement_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not row:
        raise HTTPException(404, "Supplier statement not found")
    if row.status == "reconciled":
        return {"id": row.id, "status": "already_reconciled"}
    lines = db.query(ProcurementSupplierStatementLine).filter_by(
        statement_id=row.id, organization_id=membership.organization_id
    ).all()
    unmatched = [x.id for x in lines if not x.matched_invoice_id and not x.matched_payment_id and not x.matched_credit_note_id]
    calculated = Decimal(row.opening_balance) + sum((Decimal(x.amount) for x in lines), Decimal("0.00"))
    if unmatched:
        raise HTTPException(409, {"message": "All supplier statement lines must be matched", "unmatched_line_ids": unmatched})
    if calculated != Decimal(row.closing_balance):
        raise HTTPException(409, {"message": "Supplier statement opening/closing balances do not reconcile",
                                   "calculated_closing_balance": str(calculated),
                                   "statement_closing_balance": str(row.closing_balance)})
    row.status = "reconciled"
    row.reconciled_by = user.id
    row.reconciled_at = datetime.now(timezone.utc)
    db.commit()
    audit(db, user.id, membership.organization_id, "procurement.supplier_statement.reconciled",
          "supplier_statement", row.id)
    return {"id": row.id, "status": row.status, "matched_lines": len(lines),
            "closing_balance": str(calculated)}




@router.post("/supplier-returns/{return_id}/post-credit-note", status_code=201)
def post_supplier_return_credit_note(return_id: int, payload: SupplierReturnCreditNoteIn,
                                     membership=Depends(active_membership), user: User = Depends(current_user),
                                     db: Session = Depends(get_db)):
    """Convert returned accepted goods into a posted AP credit note, tied to the source matched invoice."""
    require_permission(membership, "manage")
    duplicate = db.query(AccountingCreditNote).filter_by(
        organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
    ).first()
    if duplicate:
        if duplicate.credit_note_number != payload.credit_note_number.strip().upper():
            raise HTTPException(409, "Credit-note idempotency key was used for different data")
        return {"id": duplicate.id, "status": "already_posted" if duplicate.status == "posted" else duplicate.status,
                "journal_id": duplicate.journal_id, "total": str(duplicate.total)}
    ret = db.query(ProcurementSupplierReturn).filter_by(
        id=return_id, organization_id=membership.organization_id, status="posted"
    ).with_for_update().first()
    if not ret:
        raise HTTPException(404, "Posted supplier return not found")
    receipt = db.query(ProcurementGoodsReceipt).filter_by(
        id=ret.goods_receipt_id, organization_id=membership.organization_id, status="inspected"
    ).first()
    if not receipt:
        raise HTTPException(409, "Supplier return does not reference an inspected goods receipt")
    order = db.query(ProcurementPurchaseOrder).filter_by(
        id=receipt.purchase_order_id, organization_id=membership.organization_id, supplier_id=ret.supplier_id
    ).first()
    if not order or (order.branch_id and not can_access_branch(membership, order.branch_id)):
        raise HTTPException(404, "Purchase order not found")
    link = db.query(AccountingProcurementLink).filter_by(
        organization_id=membership.organization_id,
    ).join(ProcurementSupplierInvoice,
           ProcurementSupplierInvoice.id == AccountingProcurementLink.procurement_invoice_id).filter(
        ProcurementSupplierInvoice.purchase_order_id == order.id,
        ProcurementSupplierInvoice.supplier_id == ret.supplier_id,
    ).first()
    if not link:
        raise HTTPException(409, "No matched supplier invoice has been integrated into AP for this purchase order")
    invoice = db.query(AccountingInvoice).filter_by(
        id=link.accounting_invoice_id, organization_id=membership.organization_id,
        invoice_type="payable", supplier_id=ret.supplier_id,
    ).with_for_update().first()
    if not invoice or invoice.status not in {"posted", "partially_paid", "paid"}:
        raise HTTPException(409, "Source AP invoice must be posted before supplier credit-note posting")
    if invoice.branch_id and not can_access_branch(membership, invoice.branch_id):
        raise HTTPException(404, "Supplier invoice not found")
    _accounting_assert_period_open(db, membership.organization_id, payload.issue_date)
    return_lines = db.query(ProcurementSupplierReturnLine, ProcurementGoodsReceiptLine).join(
        ProcurementGoodsReceiptLine,
        ProcurementGoodsReceiptLine.id == ProcurementSupplierReturnLine.receipt_line_id
    ).filter(
        ProcurementSupplierReturnLine.organization_id == membership.organization_id,
        ProcurementSupplierReturnLine.return_id == ret.id,
    ).all()
    if not return_lines:
        raise HTTPException(409, "Supplier return has no return lines")
    prepared = []
    total_sub = Decimal("0.00")
    total_tax = Decimal("0.00")
    for return_line, receipt_line in return_lines:
        po_line_id = receipt_line.purchase_order_line_id
        ap_lines = db.query(AccountingInvoiceLine).filter(
            AccountingInvoiceLine.organization_id == membership.organization_id,
            AccountingInvoiceLine.invoice_id == invoice.id,
            AccountingInvoiceLine.description.contains(f"PO line {po_line_id}"),
        ).order_by(AccountingInvoiceLine.id).with_for_update().all()
        remaining_return = Decimal(return_line.quantity)
        for ap_line in ap_lines:
            if remaining_return <= 0:
                break
            prior_credited = db.query(func.coalesce(func.sum(AccountingCreditNoteLine.quantity), 0)).join(
                AccountingCreditNote, AccountingCreditNote.id == AccountingCreditNoteLine.credit_note_id
            ).filter(
                AccountingCreditNote.organization_id == membership.organization_id,
                AccountingCreditNote.invoice_id == invoice.id,
                AccountingCreditNote.status == "posted",
                AccountingCreditNoteLine.invoice_line_id == ap_line.id,
            ).scalar() or Decimal("0")
            available = Decimal(ap_line.quantity) - Decimal(prior_credited)
            take = min(remaining_return, available)
            if take <= 0:
                continue
            if take == available:
                sub = Decimal(ap_line.subtotal) - sum(
                    (Decimal(x.subtotal) for x in db.query(AccountingCreditNoteLine).join(
                        AccountingCreditNote, AccountingCreditNote.id == AccountingCreditNoteLine.credit_note_id
                    ).filter(AccountingCreditNote.invoice_id == invoice.id,
                             AccountingCreditNote.status == "posted",
                             AccountingCreditNoteLine.invoice_line_id == ap_line.id).all()), Decimal("0.00"))
                tax = Decimal(ap_line.tax_amount) - sum(
                    (Decimal(x.tax_amount) for x in db.query(AccountingCreditNoteLine).join(
                        AccountingCreditNote, AccountingCreditNote.id == AccountingCreditNoteLine.credit_note_id
                    ).filter(AccountingCreditNote.invoice_id == invoice.id,
                             AccountingCreditNote.status == "posted",
                             AccountingCreditNoteLine.invoice_line_id == ap_line.id).all()), Decimal("0.00"))
            else:
                sub = (Decimal(ap_line.subtotal) * take / Decimal(ap_line.quantity)).quantize(CENT)
                tax = (Decimal(ap_line.tax_amount) * take / Decimal(ap_line.quantity)).quantize(CENT)
            prepared.append((ap_line, take, sub, tax))
            total_sub += sub
            total_tax += tax
            remaining_return -= take
        if remaining_return > 0:
            raise HTTPException(409, f"Returned quantity for PO line {po_line_id} exceeds invoiced quantity not yet credited")
    total = total_sub + total_tax
    if total <= 0:
        raise HTTPException(409, "Supplier return has no remaining invoice value to credit")
    note = AccountingCreditNote(
        organization_id=membership.organization_id, invoice_id=invoice.id, branch_id=invoice.branch_id,
        credit_note_number=payload.credit_note_number.strip().upper(),
        issue_date=datetime.combine(payload.issue_date, time.min, tzinfo=timezone.utc),
        reason=payload.reason.strip(), currency=invoice.currency, subtotal=total_sub, tax_total=total_tax,
        total=total, status="draft", idempotency_key=payload.idempotency_key,
        created_by=user.id,
    )
    db.add(note)
    db.flush()
    journal_lines = [{"account_id": invoice.control_account_id,
                      "description": "Accounts payable reduction " + note.credit_note_number,
                      "debit": total, "credit": Decimal("0.00")}]
    for ap_line, quantity, subtotal, tax in prepared:
        db.add(AccountingCreditNoteLine(
            organization_id=membership.organization_id, credit_note_id=note.id,
            invoice_line_id=ap_line.id, quantity=quantity, subtotal=subtotal,
            tax_amount=tax, total=subtotal+tax,
        ))
        journal_lines.append({"account_id": ap_line.account_id,
                              "description": "Purchase return credit " + note.credit_note_number,
                              "debit": Decimal("0.00"), "credit": subtotal})
        if tax:
            if not ap_line.tax_account_id:
                raise HTTPException(409, "Source AP invoice line has tax but no input-tax account mapping")
            journal_lines.append({"account_id": ap_line.tax_account_id,
                                  "description": "Input tax reversal " + note.credit_note_number,
                                  "debit": Decimal("0.00"), "credit": tax})
    journal = _accounting_make_journal(
        db, membership, user, payload.issue_date, note.credit_note_number,
        "Supplier credit note " + note.credit_note_number, journal_lines, invoice.branch_id,
    )
    note.status = "posted"
    note.journal_id = journal.id
    note.posted_by = user.id
    note.posted_at = datetime.now(timezone.utc)
    invoice.total = Decimal(invoice.total) - total
    invoice.status = "paid" if Decimal(invoice.amount_paid) >= Decimal(invoice.total) else (
        "partially_paid" if Decimal(invoice.amount_paid) > 0 else "posted"
    )
    db.commit()
    audit(db, user.id, membership.organization_id, "procurement.supplier_return.credit_note_posted",
          "accounting_credit_note", note.id, f"return:{ret.id};total:{total}")
    return {"id": note.id, "credit_note_number": note.credit_note_number, "status": note.status,
            "supplier_return_id": ret.id, "accounting_invoice_id": invoice.id,
            "subtotal": str(note.subtotal), "tax_total": str(note.tax_total),
            "total": str(note.total), "journal_id": journal.id}


@router.post("/supplier-invoices/{supplier_invoice_id}/discrepancies", status_code=201)
def record_supplier_invoice_discrepancy(supplier_invoice_id: int, payload: DiscrepancyIn,
                                         membership=Depends(active_membership), user: User = Depends(current_user),
                                         db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    invoice = db.query(ProcurementSupplierInvoice).filter_by(
        id=supplier_invoice_id, organization_id=membership.organization_id
    ).first()
    if not invoice:
        raise HTTPException(404, "Supplier invoice not found")
    if invoice.status not in {"matched", "accounted"}:
        raise HTTPException(409, "Discrepancies can only be raised against a matched or accounted invoice")
    row = ProcurementInvoiceDiscrepancy(
        organization_id=membership.organization_id, supplier_invoice_id=invoice.id,
        code=payload.code, details=payload.details, status="open", created_by=user.id,
    )
    db.add(row)
    db.commit()
    audit(db, user.id, membership.organization_id, "procurement.invoice.discrepancy.opened",
          "supplier_invoice_discrepancy", row.id, payload.code)
    return {"id": row.id, "supplier_invoice_id": invoice.id, "status": row.status, "code": row.code}


@router.post("/invoice-discrepancies/{discrepancy_id}/resolve")
def resolve_supplier_invoice_discrepancy(discrepancy_id: int, payload: DiscrepancyResolveIn,
                                          membership=Depends(active_membership), user: User = Depends(current_user),
                                          db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(ProcurementInvoiceDiscrepancy).filter_by(
        id=discrepancy_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not row:
        raise HTTPException(404, "Invoice discrepancy not found")
    if row.status == "resolved":
        return {"id": row.id, "status": "already_resolved"}
    invoice = db.query(ProcurementSupplierInvoice).filter_by(
        id=row.supplier_invoice_id, organization_id=membership.organization_id
    ).first()
    if not invoice or invoice.status not in {"matched", "accounted"}:
        raise HTTPException(409, "Source invoice is not in a reconciled state")
    row.status = "resolved"
    row.resolution_note = payload.resolution_note.strip()
    row.resolved_by = user.id
    row.resolved_at = datetime.now(timezone.utc)
    db.commit()
    audit(db, user.id, membership.organization_id, "procurement.invoice.discrepancy.resolved",
          "supplier_invoice_discrepancy", row.id, row.resolution_note)
    return {"id": row.id, "status": row.status}


@router.get("/accounting-reconciliation")
def procurement_accounting_reconciliation(start_date: date | None = None, end_date: date | None = None,
                                           membership=Depends(active_membership), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    q = db.query(ProcurementSupplierInvoice).filter_by(organization_id=membership.organization_id)
    if start_date:
        q = q.filter(ProcurementSupplierInvoice.invoice_date >= datetime.combine(start_date, time.min, tzinfo=timezone.utc))
    if end_date:
        q = q.filter(ProcurementSupplierInvoice.invoice_date <= datetime.combine(end_date, time.max, tzinfo=timezone.utc))
    source = q.order_by(ProcurementSupplierInvoice.id).all()
    from app.core.models import AccountingProcurementLink, AccountingBankStatement
    links = db.query(AccountingProcurementLink).filter_by(organization_id=membership.organization_id).all()
    link_map = {x.procurement_invoice_id: x for x in links}
    settlements = db.query(ProcurementSettlement).filter_by(
        organization_id=membership.organization_id, status="settled"
    ).all()
    statement_lines = db.query(AccountingBankStatementLine).filter_by(
        organization_id=membership.organization_id
    ).all()
    bank_matched_journal_ids = {x.matched_journal_line_id for x in statement_lines if x.matched_journal_line_id}
    result = []
    blockers = []
    for item in source:
        link = link_map.get(item.id)
        ap = db.query(AccountingInvoice).filter_by(
            id=link.accounting_invoice_id, organization_id=membership.organization_id
        ).first() if link else None
        row = {"procurement_invoice_id": item.id, "supplier_invoice_number": item.invoice_number,
               "source_status": item.status, "accounting_invoice_id": ap.id if ap else None,
               "ap_status": ap.status if ap else "not_integrated",
               "source_total": str(Decimal(item.subtotal)+Decimal(item.tax_total)),
               "ap_total": str(ap.total) if ap else None}
        if not ap:
            blockers.append({"invoice_id": item.id, "reason": "not_integrated_to_ap"})
        elif Decimal(ap.total) != Decimal(item.subtotal)+Decimal(item.tax_total):
            blockers.append({"invoice_id": item.id, "reason": "source_ap_total_mismatch"})
        result.append(row)
    return {
        "supplier_invoices": result,
        "settled_supplier_payments": len(settlements),
        "bank_statement_lines": len(statement_lines),
        "bank_matched_lines": len(bank_matched_journal_ids),
        "unmatched_bank_lines": len(statement_lines)-len(bank_matched_journal_ids),
        "blockers": blockers,
        "ready": not blockers and len(statement_lines) == len(bank_matched_journal_ids),
        "note": "Bank matching is evidenced by matched journal-line references; provider callbacks and live bank feeds require configured production credentials and provider UAT.",
    }
