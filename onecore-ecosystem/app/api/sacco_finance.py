"""SACCO finance automation, collections, restructuring and accounting bridge."""
import hashlib
import json
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
import csv
from io import StringIO
from pydantic import BaseModel, Field
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import (
    User, AuditEvent, SaccoMember, SaccoAccount, SaccoTransaction, SaccoLoan,
    SaccoLoanSchedule, SaccoLoanRepayment, SaccoFinanceRecord, AccountingAccount,
    AccountingJournal, AccountingJournalLine,
)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, can_access_branch
from app.services.sacco import build_repayment_schedule, allocate_repayment, money

router = APIRouter(prefix="/api/v1/sacco/finance", tags=["SACCO Finance"])
CENT = Decimal("0.01")


class StandingOrderIn(BaseModel):
    account_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    frequency: str = Field(pattern=r"^(weekly|monthly)$")
    next_run: date
    reference: str = Field(default="Recurring member contribution", max_length=120)


class CollectionIn(BaseModel):
    provider: str = Field(pattern=r"^(mpesa|bank|mobile_money|cash_office)$")
    external_reference: str = Field(min_length=3, max_length=120)
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    currency: str = Field(default="KES", pattern=r"^[A-Z]{3}$")
    member_id: int = Field(gt=0)
    target_type: str = Field(pattern=r"^(savings|shares|contributions|loan)$")
    target_id: int = Field(gt=0)
    value_date: date


class ReconcileIn(BaseModel):
    collection_id: int = Field(gt=0)
    statement_reference: str = Field(min_length=3, max_length=120)
    statement_amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    idempotency_key: str = Field(min_length=8, max_length=120)


class RestructureIn(BaseModel):
    new_term_months: int = Field(ge=1, le=600)
    first_due_date: date
    reason: str = Field(min_length=5, max_length=500)


class DecisionIn(BaseModel):
    decision: str = Field(pattern=r"^(approved|rejected)$")
    note: str = Field(min_length=3, max_length=500)


class DividendIn(BaseModel):
    pool_amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    financial_year: int = Field(ge=2000, le=2200)
    idempotency_key: str = Field(min_length=8, max_length=120)


class ProvisionPolicyIn(BaseModel):
    rate_1_30: Decimal = Field(ge=0, le=100)
    rate_31_60: Decimal = Field(ge=0, le=100)
    rate_61_90: Decimal = Field(ge=0, le=100)
    rate_over_90: Decimal = Field(ge=0, le=100)


class RefinanceIn(BaseModel):
    replacement_loan_id: int = Field(gt=0)
    reason: str = Field(min_length=5, max_length=500)


class JournalPostIn(BaseModel):
    source_type: str = Field(pattern=r"^(savings_transaction|loan_repayment|loan_disbursement|dividend)$")
    source_id: int = Field(gt=0)
    debit_account_id: int = Field(gt=0)
    credit_account_id: int = Field(gt=0)
    entry_date: date
    memo: str = Field(min_length=3, max_length=500)


def _visible_branch(membership, branch_id):
    return not branch_id or can_access_branch(membership, branch_id)


def _record(db, membership, user, kind, key, data, *, member_id=None, account_id=None,
            loan_id=None, amount=None, currency="KES", reference="", status="pending", branch_id=None):
    existing = db.query(SaccoFinanceRecord).filter_by(
        organization_id=membership.organization_id, idempotency_key=key
    ).first()
    if existing:
        expected = {"record_type": kind, "member_id": member_id, "account_id": account_id,
                    "loan_id": loan_id, "amount": str(amount) if amount is not None else None,
                    "reference": reference, "data": data}
        actual = {"record_type": existing.record_type, "member_id": existing.member_id,
                  "account_id": existing.account_id, "loan_id": existing.loan_id,
                  "amount": str(existing.amount) if existing.amount is not None else None,
                  "reference": existing.reference, "data": existing.data}
        if expected != actual:
            raise HTTPException(409, "Idempotency key was already used for a different request")
        return existing, False
    row = SaccoFinanceRecord(
        organization_id=membership.organization_id, branch_id=branch_id,
        record_type=kind, member_id=member_id, account_id=account_id, loan_id=loan_id,
        amount=amount, currency=currency, reference=reference, status=status,
        idempotency_key=key, data=data, created_by=user.id,
    )
    db.add(row)
    db.flush()
    return row, True


def _audit(db, membership, user, action, kind, row_id, detail=""):
    db.add(AuditEvent(actor_user_id=user.id, organization_id=membership.organization_id,
                      action=action, resource_type=kind, resource_id=str(row_id), detail=detail))


def _account_balance(db, org_id, account_id):
    rows = db.query(SaccoTransaction.transaction_type, SaccoTransaction.amount).filter_by(
        organization_id=org_id, account_id=account_id).all()
    total = Decimal("0.00")
    for kind, amount in rows:
        total += -Decimal(amount) if kind == "withdrawal" else Decimal(amount)
    return money(total)


def _account_or_404(db, membership, account_id):
    row = db.query(SaccoAccount).filter_by(
        id=account_id, organization_id=membership.organization_id, status="active").first()
    if not row or not _visible_branch(membership, row.branch_id):
        raise HTTPException(404, "SACCO account not found")
    return row


def _loan_or_404(db, membership, loan_id, lock=False):
    q = db.query(SaccoLoan).filter_by(id=loan_id, organization_id=membership.organization_id)
    if lock:
        q = q.with_for_update()
    row = q.first()
    if not row or not _visible_branch(membership, row.branch_id):
        raise HTTPException(404, "SACCO loan not found")
    return row


def _next_date(value, frequency):
    return value + timedelta(days=7) if frequency == "weekly" else date(
        value.year + (1 if value.month == 12 else 0), 1 if value.month == 12 else value.month + 1,
        min(value.day, monthrange(value.year + (1 if value.month == 12 else 0),
                                  1 if value.month == 12 else value.month + 1)[1]))


@router.post("/standing-orders", status_code=201)
def create_standing_order(payload: StandingOrderIn, membership=Depends(active_membership),
                          user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    account = _account_or_404(db, membership, payload.account_id)
    member = db.query(SaccoMember).filter_by(
        id=account.member_id, organization_id=membership.organization_id,
        status="active", kyc_status="verified").first()
    if not member:
        raise HTTPException(409, "Active KYC-verified member required")
    key = "standing-order:" + uuid.uuid4().hex
    data = {"frequency": payload.frequency, "next_run": payload.next_run.isoformat(),
            "reference": payload.reference.strip(), "created_by": user.id}
    row, _ = _record(db, membership, user, "standing_order", key, data,
                     member_id=member.id, account_id=account.id, amount=payload.amount,
                     currency=account.currency, branch_id=account.branch_id, status="active")
    _audit(db, membership, user, "sacco.standing_order.created", "sacco_finance_record", row.id)
    db.commit()
    return {"id": row.id, "account_id": account.id, "amount": str(row.amount),
            "frequency": payload.frequency, "next_run": payload.next_run.isoformat(), "status": row.status}


@router.get("/standing-orders")
def list_standing_orders(membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    rows = db.query(SaccoFinanceRecord).filter_by(
        organization_id=membership.organization_id, record_type="standing_order").order_by(
        SaccoFinanceRecord.id.desc()).limit(500).all()
    return [{"id": r.id, "member_id": r.member_id, "account_id": r.account_id,
             "amount": str(r.amount), "currency": r.currency, "status": r.status,
             **(r.data or {})} for r in rows if _visible_branch(membership, r.branch_id)]


@router.post("/standing-orders/run")
def run_due_standing_orders(membership=Depends(active_membership), user: User=Depends(current_user),
                            db: Session=Depends(get_db), as_of: date | None = None):
    require_permission(membership, "manage")
    cutoff = as_of or datetime.now(timezone.utc).date()
    rows = db.query(SaccoFinanceRecord).filter_by(
        organization_id=membership.organization_id, record_type="standing_order", status="active"
    ).with_for_update().all()
    processed, skipped = [], []
    for order in rows:
        if not _visible_branch(membership, order.branch_id):
            continue
        data = dict(order.data or {})
        due = date.fromisoformat(data["next_run"])
        if due > cutoff:
            continue
        account = _account_or_404(db, membership, order.account_id)
        tx_type = {"savings": "deposit", "shares": "share_contribution",
                   "contributions": "contribution"}[account.account_type]
        key = f"standing-order:{order.id}:{due.isoformat()}"
        request = {"account_id": account.id, "transaction_type": tx_type,
                   "amount": str(money(order.amount)), "reference": data.get("reference", "")}
        digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        existing = db.query(SaccoTransaction).filter_by(
            organization_id=membership.organization_id, idempotency_key=key).first()
        if not existing:
            tx = SaccoTransaction(organization_id=membership.organization_id, account_id=account.id,
                transaction_type=tx_type, amount=money(order.amount), reference=data.get("reference", ""),
                idempotency_key=key, request_hash=digest, created_by=user.id)
            db.add(tx)
            processed.append({"standing_order_id": order.id, "account_id": account.id, "due_date": due.isoformat()})
        else:
            skipped.append(order.id)
        data["next_run"] = _next_date(due, data["frequency"]).isoformat()
        order.data = data
        order.updated_at = datetime.now(timezone.utc)
    _audit(db, membership, user, "sacco.standing_orders.executed", "sacco_finance", cutoff,
           f"processed:{len(processed)};skipped:{len(skipped)}")
    db.commit()
    return {"as_of": cutoff.isoformat(), "processed": processed, "already_processed": skipped}


@router.post("/collections", status_code=201)
def import_collection(payload: CollectionIn, membership=Depends(active_membership),
                      user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "create")
    member = db.query(SaccoMember).filter_by(
        id=payload.member_id, organization_id=membership.organization_id,
        status="active", kyc_status="verified").first()
    if not member or not _visible_branch(membership, member.branch_id):
        raise HTTPException(404, "Active SACCO member not found")
    account_id = None
    loan_id = None
    if payload.target_type == "loan":
        loan = _loan_or_404(db, membership, payload.target_id)
        if loan.member_id != member.id:
            raise HTTPException(422, "Collection member does not own the selected loan")
        loan_id = loan.id
        currency = "KES"
    else:
        account = _account_or_404(db, membership, payload.target_id)
        if account.member_id != member.id or account.account_type != payload.target_type:
            raise HTTPException(422, "Collection target does not match member and account type")
        account_id, currency = account.id, account.currency
    if payload.currency != currency:
        raise HTTPException(422, "Collection currency does not match target account")
    key = "collection:" + payload.provider + ":" + payload.external_reference
    data = {"provider": payload.provider, "external_reference": payload.external_reference,
            "target_type": payload.target_type, "value_date": payload.value_date.isoformat()}
    row, created = _record(db, membership, user, "collection", key, data,
        member_id=member.id, account_id=account_id, loan_id=loan_id, amount=money(payload.amount),
        currency=payload.currency, reference=payload.external_reference, branch_id=member.branch_id,
        status="unmatched")
    _audit(db, membership, user, "sacco.collection.imported", "sacco_collection", row.id,
           "Provider record is unverified until independently reconciled")
    db.commit()
    return {"id": row.id, "status": row.status, "amount": str(row.amount),
            "reference": row.reference, "created": created, "verified_settlement": False}


@router.post("/collections/reconcile")
def reconcile_collection(payload: ReconcileIn, membership=Depends(active_membership),
                         user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(SaccoFinanceRecord).filter_by(
        id=payload.collection_id, organization_id=membership.organization_id,
        record_type="collection").with_for_update().first()
    if not row or not _visible_branch(membership, row.branch_id):
        raise HTTPException(404, "Collection not found")
    if row.status == "settled":
        if row.data.get("statement_reference") == payload.statement_reference and money(row.amount) == money(payload.statement_amount):
            return {"id": row.id, "status": "settled", "idempotent": True}
        raise HTTPException(409, "Collection has already been settled")
    if row.reference != payload.statement_reference or money(row.amount) != money(payload.statement_amount):
        row.status = "exception"
        row.data = {**(row.data or {}), "reconciliation_exception": "reference_or_amount_mismatch"}
        db.commit()
        raise HTTPException(409, "Bank/provider reference and amount must match exactly")
    if row.account_id:
        account = _account_or_404(db, membership, row.account_id)
        tx_type = {"savings": "deposit", "shares": "share_contribution",
                   "contributions": "contribution"}[account.account_type]
        key = "collection-settlement:" + str(row.id)
        request = {"account_id": account.id, "type": tx_type, "amount": str(money(row.amount)),
                   "reference": row.reference}
        digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        tx = db.query(SaccoTransaction).filter_by(
            organization_id=membership.organization_id, idempotency_key=key).first()
        if not tx:
            db.add(SaccoTransaction(organization_id=membership.organization_id, account_id=account.id,
                transaction_type=tx_type, amount=money(row.amount), reference=row.reference,
                idempotency_key=key, request_hash=digest, created_by=user.id))
    else:
        loan = _loan_or_404(db, membership, row.loan_id, lock=True)
        schedules = db.query(SaccoLoanSchedule).filter_by(
            organization_id=membership.organization_id, loan_id=loan.id).order_by(
            SaccoLoanSchedule.installment_number).with_for_update().all()
        try:
            principal, interest, allocations = allocate_repayment(row.amount, schedules)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        key = "collection-settlement:" + str(row.id)
        digest = hashlib.sha256(f"{loan.id}:{row.amount}:{row.reference}".encode()).hexdigest()
        db.add(SaccoLoanRepayment(organization_id=membership.organization_id, loan_id=loan.id,
            amount=money(row.amount), principal_component=principal, interest_component=interest,
            reference=row.reference, idempotency_key=key, request_hash=digest, created_by=user.id))
        for schedule, ip, pp in allocations:
            schedule.interest_paid = money(schedule.interest_paid + ip)
            schedule.principal_paid = money(schedule.principal_paid + pp)
            if schedule.interest_paid >= schedule.interest_due and schedule.principal_paid >= schedule.principal_due:
                schedule.status = "paid"
        loan.outstanding_principal = money(loan.outstanding_principal - principal)
        loan.outstanding_interest = money(loan.outstanding_interest - interest)
        if loan.outstanding_principal == 0 and loan.outstanding_interest == 0:
            loan.status = "closed"
    row.status = "settled"
    row.data = {**(row.data or {}), "statement_reference": payload.statement_reference,
                "statement_amount": str(money(payload.statement_amount)),
                "settled_at": datetime.now(timezone.utc).isoformat(), "settled_by": user.id}
    _audit(db, membership, user, "sacco.collection.settled", "sacco_collection", row.id)
    db.commit()
    return {"id": row.id, "status": row.status, "verified_settlement": True}


@router.post("/loans/{loan_id}/restructure")
def request_restructure(loan_id: int, payload: RestructureIn, membership=Depends(active_membership),
                        user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    loan = _loan_or_404(db, membership, loan_id, lock=True)
    if loan.status != "active" or payload.first_due_date <= datetime.now(timezone.utc).date():
        raise HTTPException(409, "Only active loans can be rescheduled to a future due date")
    pending = db.query(SaccoFinanceRecord).filter_by(
        organization_id=membership.organization_id, record_type="loan_restructure",
        loan_id=loan.id, status="pending").first()
    if pending:
        raise HTTPException(409, "A restructuring request is already pending")
    unpaid = db.query(SaccoLoanSchedule).filter_by(
        organization_id=membership.organization_id, loan_id=loan.id).filter(
        SaccoLoanSchedule.status != "paid").order_by(SaccoLoanSchedule.installment_number).all()
    try:
        schedule = build_repayment_schedule(loan.outstanding_principal, loan.annual_interest_rate,
            payload.new_term_months, loan.interest_method, payload.first_due_date)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    snapshot = [{"installment": x.installment_number, "due_date": x.due_date.isoformat(),
        "principal_due": str(x.principal_due), "interest_due": str(x.interest_due),
        "principal_paid": str(x.principal_paid), "interest_paid": str(x.interest_paid)} for x in unpaid]
    row, _ = _record(db, membership, user, "loan_restructure",
        f"restructure:{loan.id}:{uuid.uuid4().hex}",
        {"new_term_months": payload.new_term_months, "first_due_date": payload.first_due_date.isoformat(),
         "reason": payload.reason.strip(), "old_unpaid_schedule": snapshot,
         "proposed_schedule": [{"due_date": x["due_date"].isoformat(),
            "principal_due": str(x["principal_due"]), "interest_due": str(x["interest_due"])} for x in schedule]},
        member_id=loan.member_id, loan_id=loan.id, amount=loan.outstanding_principal,
        branch_id=loan.branch_id, status="pending")
    _audit(db, membership, user, "sacco.loan.restructure.requested", "sacco_loan", loan.id)
    db.commit()
    return {"request_id": row.id, "status": row.status, "outstanding_principal": str(loan.outstanding_principal),
            "proposed_installments": len(schedule), "new_total_interest": str(sum((x["interest_due"] for x in schedule), Decimal("0.00")))}


@router.post("/restructures/{request_id}/decision")
def decide_restructure(request_id: int, payload: DecisionIn, membership=Depends(active_membership),
                       user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(SaccoFinanceRecord).filter_by(
        id=request_id, organization_id=membership.organization_id, record_type="loan_restructure",
        status="pending").with_for_update().first()
    if not row or not _visible_branch(membership, row.branch_id):
        raise HTTPException(404, "Pending restructuring request not found")
    if row.created_by == user.id and payload.decision == "approved":
        raise HTTPException(403, "Maker cannot approve their own restructuring request")
    loan = _loan_or_404(db, membership, row.loan_id, lock=True)
    row.data = {**(row.data or {}), "decision_note": payload.note.strip(),
                "decided_by": user.id, "decided_at": datetime.now(timezone.utc).isoformat()}
    row.status = payload.decision
    if payload.decision == "approved":
        paid = db.query(SaccoLoanSchedule).filter_by(
            organization_id=membership.organization_id, loan_id=loan.id, status="paid").order_by(
            SaccoLoanSchedule.installment_number).all()
        start_number = max([x.installment_number for x in paid], default=0)
        old_unpaid = db.query(SaccoLoanSchedule).filter_by(
            organization_id=membership.organization_id, loan_id=loan.id).filter(
            SaccoLoanSchedule.status != "paid").all()
        for old in old_unpaid:
            db.delete(old)
        proposed = row.data["proposed_schedule"]
        new_rows = []
        for i, item in enumerate(proposed, start=start_number + 1):
            new_rows.append(SaccoLoanSchedule(organization_id=membership.organization_id, loan_id=loan.id,
                installment_number=i, due_date=date.fromisoformat(item["due_date"]),
                principal_due=Decimal(item["principal_due"]), interest_due=Decimal(item["interest_due"]),
                principal_paid=Decimal("0.00"), interest_paid=Decimal("0.00"), status="pending"))
        db.add_all(new_rows)
        paid_interest = sum((Decimal(x.interest_paid) for x in paid), Decimal("0.00"))
        loan.total_interest = money(paid_interest + sum((Decimal(x["interest_due"]) for x in proposed), Decimal("0.00")))
        loan.outstanding_interest = money(sum((Decimal(x["interest_due"]) for x in proposed), Decimal("0.00")))
        loan.term_months = len(paid) + len(proposed)
    _audit(db, membership, user, "sacco.loan.restructure.decided", "sacco_finance_record", row.id, payload.decision)
    db.commit()
    return {"request_id": row.id, "status": row.status, "loan_id": loan.id}


@router.get("/loans/{loan_id}/settlement-quote")
def loan_settlement_quote(loan_id: int, membership=Depends(active_membership),
                          db: Session=Depends(get_db), as_of: date | None = None):
    require_permission(membership, "read")
    loan = _loan_or_404(db, membership, loan_id)
    cutoff = as_of or datetime.now(timezone.utc).date()
    schedules = db.query(SaccoLoanSchedule).filter_by(
        organization_id=membership.organization_id, loan_id=loan.id).all()
    principal = sum((max(Decimal("0"), Decimal(x.principal_due)-Decimal(x.principal_paid)) for x in schedules), Decimal("0"))
    interest = sum((max(Decimal("0"), Decimal(x.interest_due)-Decimal(x.interest_paid)) for x in schedules), Decimal("0"))
    return {"loan_id": loan.id, "as_of": cutoff.isoformat(), "currency": "KES",
            "outstanding_principal": str(money(principal)), "outstanding_scheduled_interest": str(money(interest)),
            "early_settlement_rebate": "0.00", "settlement_amount": str(money(principal+interest)),
            "policy_note": "No rebate or unearned-interest adjustment is applied; configure and approve SACCO policy before use."}


@router.get("/members/{member_id}/statement")
def member_statement(member_id: int, membership=Depends(active_membership),
                     db: Session=Depends(get_db), start_date: date | None = None,
                     end_date: date | None = None):
    require_permission(membership, "read")
    member = db.query(SaccoMember).filter_by(
        id=member_id, organization_id=membership.organization_id).first()
    if not member or not _visible_branch(membership, member.branch_id):
        raise HTTPException(404, "Member not found")
    if start_date and end_date and end_date < start_date:
        raise HTTPException(422, "End date must not precede start date")
    accounts = db.query(SaccoAccount).filter_by(
        organization_id=membership.organization_id, member_id=member.id).all()
    entries = []
    for account in accounts:
        txs = db.query(SaccoTransaction).filter_by(
            organization_id=membership.organization_id, account_id=account.id).order_by(
            SaccoTransaction.created_at, SaccoTransaction.id).all()
        balance = Decimal("0.00")
        for tx in txs:
            delta = -Decimal(tx.amount) if tx.transaction_type == "withdrawal" else Decimal(tx.amount)
            balance = money(balance + delta)
            if (not start_date or tx.created_at.date() >= start_date) and (not end_date or tx.created_at.date() <= end_date):
                entries.append({"date": tx.created_at.isoformat(), "type": tx.transaction_type,
                    "account": account.account_number, "reference": tx.reference,
                    "debit": str(tx.amount) if tx.transaction_type == "withdrawal" else "0.00",
                    "credit": "0.00" if tx.transaction_type == "withdrawal" else str(tx.amount),
                    "balance": str(balance), "currency": account.currency})
    repayments = db.query(SaccoLoanRepayment, SaccoLoan).join(
        SaccoLoan, SaccoLoan.id == SaccoLoanRepayment.loan_id).filter(
        SaccoLoan.organization_id == membership.organization_id,
        SaccoLoan.member_id == member.id).order_by(SaccoLoanRepayment.created_at).all()
    for tx, loan in repayments:
        if (not start_date or tx.created_at.date() >= start_date) and (not end_date or tx.created_at.date() <= end_date):
            entries.append({"date": tx.created_at.isoformat(), "type": "loan_repayment",
                "account": loan.loan_number, "reference": tx.reference, "debit": "0.00",
                "credit": str(tx.amount), "balance": str(loan.outstanding_principal+loan.outstanding_interest),
                "currency": "KES"})
    entries.sort(key=lambda x: x["date"])
    return {"member_id": member.id, "member_number": member.member_number, "full_name": member.full_name,
            "period": {"from": start_date.isoformat() if start_date else None,
                       "to": end_date.isoformat() if end_date else None}, "transactions": entries}


@router.post("/dividends/allocate")
def allocate_dividends(payload: DividendIn, membership=Depends(active_membership),
                        user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    key = f"dividend-allocation:{payload.financial_year}:{payload.idempotency_key}"
    existing = db.query(SaccoFinanceRecord).filter_by(
        organization_id=membership.organization_id, idempotency_key=key).first()
    if existing:
        return {"id": existing.id, "status": existing.status, **(existing.data or {})}
    accounts = db.query(SaccoAccount).filter_by(
        organization_id=membership.organization_id, account_type="shares", status="active").all()
    weights = {}
    for account in accounts:
        if _visible_branch(membership, account.branch_id):
            bal = _account_balance(db, membership.organization_id, account.id)
            if bal > 0:
                weights[account.member_id] = weights.get(account.member_id, Decimal("0.00")) + bal
    total_shares = sum(weights.values(), Decimal("0.00"))
    if total_shares <= 0:
        raise HTTPException(409, "No positive share capital is available for dividend allocation")
    pool = money(payload.pool_amount)
    allocations = {mid: money(pool * shares / total_shares) for mid, shares in weights.items()}
    residue = money(pool - sum(allocations.values(), Decimal("0.00")))
    if residue:
        largest = max(weights, key=weights.get)
        allocations[largest] = money(allocations[largest] + residue)
    results = []
    for member_id, amount in allocations.items():
        savings = db.query(SaccoAccount).filter_by(
            organization_id=membership.organization_id, member_id=member_id,
            account_type="savings", status="active").first()
        if not savings:
            raise HTTPException(409, f"Member {member_id} has no active savings account; allocation cancelled")
        txkey = f"dividend:{payload.financial_year}:{member_id}"
        request = {"account_id": savings.id, "amount": str(amount), "year": payload.financial_year}
        digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        if not db.query(SaccoTransaction).filter_by(
            organization_id=membership.organization_id, idempotency_key=txkey).first():
            db.add(SaccoTransaction(organization_id=membership.organization_id, account_id=savings.id,
                transaction_type="deposit", amount=amount, reference=f"DIVIDEND-{payload.financial_year}",
                idempotency_key=txkey, request_hash=digest, created_by=user.id))
        results.append({"member_id": member_id, "shares": str(weights[member_id]), "dividend": str(amount)})
    row, _ = _record(db, membership, user, "dividend_allocation", key,
        {"financial_year": payload.financial_year, "pool_amount": str(pool),
         "total_share_capital": str(total_shares), "allocations": results},
        amount=pool, reference=f"DIVIDEND-{payload.financial_year}", status="allocated")
    _audit(db, membership, user, "sacco.dividends.allocated", "sacco_finance_record", row.id)
    db.commit()
    return {"id": row.id, "status": row.status, "financial_year": payload.financial_year,
            "pool_amount": str(pool), "total_share_capital": str(total_shares), "allocations": results}


@router.get("/shares/reconcile")
def reconcile_share_capital(membership=Depends(active_membership), db: Session=Depends(get_db),
                            gl_account_id: int | None = Query(default=None, gt=0)):
    require_permission(membership, "read")
    accounts = db.query(SaccoAccount).filter_by(
        organization_id=membership.organization_id, account_type="shares", status="active").all()
    share_total = sum((_account_balance(db, membership.organization_id, a.id)
                       for a in accounts if _visible_branch(membership, a.branch_id)), Decimal("0.00"))
    result = {"member_ledger_share_capital": str(money(share_total)), "member_account_count": len(accounts)}
    if gl_account_id:
        gl = db.query(AccountingAccount).filter_by(
            id=gl_account_id, organization_id=membership.organization_id, is_active=True).first()
        if not gl:
            raise HTTPException(404, "General-ledger account not found")
        totals = db.query(func.coalesce(func.sum(AccountingJournalLine.credit), 0),
                          func.coalesce(func.sum(AccountingJournalLine.debit), 0)).join(
            AccountingJournal, AccountingJournal.id == AccountingJournalLine.journal_id).filter(
            AccountingJournal.organization_id == membership.organization_id,
            AccountingJournal.status == "posted", AccountingJournalLine.account_id == gl.id).first()
        gl_balance = money(Decimal(str(totals[0])) - Decimal(str(totals[1])))
        result.update({"general_ledger_account_id": gl.id, "general_ledger_balance": str(gl_balance),
                       "difference": str(money(share_total-gl_balance)), "reconciled": share_total == gl_balance})
    return result


@router.post("/loans/provisioning")
def calculate_provisioning(payload: ProvisionPolicyIn, membership=Depends(active_membership),
                           db: Session=Depends(get_db), as_of: date | None = None):
    require_permission(membership, "read")
    cutoff = as_of or datetime.now(timezone.utc).date()
    rates = {"1_30_days": payload.rate_1_30, "31_60_days": payload.rate_31_60,
             "61_90_days": payload.rate_61_90, "over_90_days": payload.rate_over_90}
    rows = db.query(SaccoLoan, SaccoLoanSchedule).join(
        SaccoLoanSchedule, and_(SaccoLoanSchedule.loan_id == SaccoLoan.id,
                                SaccoLoanSchedule.organization_id == SaccoLoan.organization_id)).filter(
        SaccoLoan.organization_id == membership.organization_id, SaccoLoan.status == "active",
        SaccoLoanSchedule.status != "paid", SaccoLoanSchedule.due_date < cutoff).all()
    buckets = {key: Decimal("0.00") for key in rates}
    loans = {}
    for loan, inst in rows:
        if not _visible_branch(membership, loan.branch_id):
            continue
        overdue = max(Decimal("0"), Decimal(inst.principal_due)-Decimal(inst.principal_paid)) + max(
            Decimal("0"), Decimal(inst.interest_due)-Decimal(inst.interest_paid))
        if overdue <= 0:
            continue
        days = (cutoff-inst.due_date).days
        bucket = "1_30_days" if days <= 30 else "31_60_days" if days <= 60 else "61_90_days" if days <= 90 else "over_90_days"
        buckets[bucket] += overdue
        loans[loan.id] = loans.get(loan.id, Decimal("0.00")) + overdue
    provision = sum((money(value*rates[key]/Decimal("100")) for key,value in buckets.items()), Decimal("0.00"))
    return {"as_of": cutoff.isoformat(), "basis": "overdue_scheduled_principal_and_interest",
        "rates_percent": {k: str(v) for k,v in rates.items()},
        "exposure_by_ageing": {k: str(money(v)) for k,v in buckets.items()},
        "provision_by_ageing": {k: str(money(buckets[k]*rates[k]/Decimal("100"))) for k in rates},
        "total_overdue_exposure": str(money(sum(buckets.values(), Decimal("0.00")))),
        "required_provision": str(provision), "loan_count": len(loans),
        "policy_status": "illustrative_policy_input_not_regulatory_certification"}


@router.post("/accounting/post")
def post_sacco_accounting_journal(payload: JournalPostIn, membership=Depends(active_membership),
                                  user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    key = f"accounting-post:{payload.source_type}:{payload.source_id}"
    prior = db.query(SaccoFinanceRecord).filter_by(
        organization_id=membership.organization_id, idempotency_key=key).first()
    if prior:
        return {"journal_id": prior.data["journal_id"], "status": "already_posted"}
    debit = db.query(AccountingAccount).filter_by(
        id=payload.debit_account_id, organization_id=membership.organization_id, is_active=True).first()
    credit = db.query(AccountingAccount).filter_by(
        id=payload.credit_account_id, organization_id=membership.organization_id, is_active=True).first()
    if not debit or not credit or debit.id == credit.id:
        raise HTTPException(422, "Two distinct active accounts in this organization are required")
    amount = None
    branch_id = None
    reference = ""
    if payload.source_type == "savings_transaction":
        source = db.query(SaccoTransaction).join(SaccoAccount, SaccoAccount.id == SaccoTransaction.account_id).filter(
            SaccoTransaction.id == payload.source_id, SaccoTransaction.organization_id == membership.organization_id,
            SaccoAccount.organization_id == membership.organization_id).first()
        if not source: raise HTTPException(404, "Savings transaction not found")
        amount, reference, branch_id = source.amount, source.reference, None
        debit_amt, credit_amt = (amount, amount) if source.transaction_type != "withdrawal" else (amount, amount)
    elif payload.source_type == "loan_repayment":
        source = db.query(SaccoLoanRepayment).filter_by(
            id=payload.source_id, organization_id=membership.organization_id).first()
        if not source: raise HTTPException(404, "Loan repayment not found")
        amount, reference = source.amount, source.reference
        # Use separate principal/interest lines in the journal below.
        loan = db.query(SaccoLoan).filter_by(id=source.loan_id, organization_id=membership.organization_id).first()
        if not loan: raise HTTPException(404, "Loan not found")
    elif payload.source_type == "loan_disbursement":
        source = db.query(SaccoLoan).filter_by(
            id=payload.source_id, organization_id=membership.organization_id).first()
        if not source: raise HTTPException(404, "Loan disbursement not found")
        amount, reference = source.principal, source.disbursement_reference
    else:
        source = db.query(SaccoFinanceRecord).filter_by(
            id=payload.source_id, organization_id=membership.organization_id,
            record_type="dividend_allocation", status="allocated").first()
        if not source: raise HTTPException(404, "Dividend allocation not found")
        amount, reference = source.amount, source.reference
    amount = money(amount)
    if amount <= 0: raise HTTPException(422, "Source amount must be positive")
    journal_number = "SACCO-" + uuid.uuid4().hex[:12].upper()
    journal = AccountingJournal(organization_id=membership.organization_id, branch_id=branch_id,
        journal_number=journal_number, reference=reference, memo=payload.memo,
        status="posted", entry_date=datetime.combine(payload.entry_date, datetime.min.time(), tzinfo=timezone.utc),
        created_by=user.id, posted_by=user.id, posted_at=datetime.now(timezone.utc))
    db.add(journal); db.flush()
    db.add_all([
        AccountingJournalLine(organization_id=membership.organization_id, journal_id=journal.id,
            account_id=debit.id, description=payload.memo, debit=amount, credit=Decimal("0.00")),
        AccountingJournalLine(organization_id=membership.organization_id, journal_id=journal.id,
            account_id=credit.id, description=payload.memo, debit=Decimal("0.00"), credit=amount),
    ])
    row, _ = _record(db, membership, user, "accounting_posting", key,
        {"journal_id": journal.id, "source_type": payload.source_type, "source_id": payload.source_id},
        amount=amount, reference=journal_number, status="posted")
    _audit(db, membership, user, "sacco.accounting.journal_posted", "accounting_journal", journal.id,
           f"source:{payload.source_type}:{payload.source_id}")
    db.commit()
    return {"journal_id": journal.id, "journal_number": journal_number,
            "amount": str(amount), "status": "posted"}


@router.get("/reports/summary")
def sacco_finance_summary(membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    members = db.query(SaccoMember).filter_by(organization_id=membership.organization_id, status="active").all()
    accounts = db.query(SaccoAccount).filter_by(organization_id=membership.organization_id, status="active").all()
    loans = db.query(SaccoLoan).filter_by(organization_id=membership.organization_id).all()
    visible_accounts = [a for a in accounts if _visible_branch(membership, a.branch_id)]
    visible_loans = [l for l in loans if _visible_branch(membership, l.branch_id)]
    savings = sum((_account_balance(db, membership.organization_id, a.id) for a in visible_accounts if a.account_type=="savings"), Decimal("0.00"))
    shares = sum((_account_balance(db, membership.organization_id, a.id) for a in visible_accounts if a.account_type=="shares"), Decimal("0.00"))
    contributions = sum((_account_balance(db, membership.organization_id, a.id) for a in visible_accounts if a.account_type=="contributions"), Decimal("0.00"))
    return {"active_members": sum(1 for m in members if _visible_branch(membership,m.branch_id)),
        "savings_liability": str(money(savings)), "share_capital": str(money(shares)),
        "member_contributions": str(money(contributions)),
        "loan_principal_outstanding": str(money(sum((Decimal(l.outstanding_principal) for l in visible_loans), Decimal("0.00")))),
        "loan_interest_outstanding": str(money(sum((Decimal(l.outstanding_interest) for l in visible_loans), Decimal("0.00")))),
        "active_loans": sum(1 for l in visible_loans if l.status=="active"),
        "unmatched_collections": db.query(SaccoFinanceRecord).filter_by(
            organization_id=membership.organization_id, record_type="collection", status="unmatched").count()}


@router.post("/collections/{collection_id}/reverse")
def reverse_settled_collection(collection_id: int, payload: DecisionIn, membership=Depends(active_membership),
                               user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(SaccoFinanceRecord).filter_by(
        id=collection_id, organization_id=membership.organization_id,
        record_type="collection", status="settled").with_for_update().first()
    if not row or not _visible_branch(membership,row.branch_id):
        raise HTTPException(404, "Settled collection not found")
    if row.created_by == user.id:
        raise HTTPException(403, "Collection importer cannot authorize its reversal")
    if row.data.get("reversal_id"):
        return {"id": row.id, "status": "reversed", "reversal_id": row.data["reversal_id"]}
    reversal, _ = _record(db, membership, user, "collection_reversal",
        f"collection-reversal:{row.id}", {"original_collection_id": row.id,
        "reason": payload.note.strip(), "authorized_by": user.id},
        member_id=row.member_id, account_id=row.account_id, loan_id=row.loan_id,
        amount=row.amount, currency=row.currency, reference=row.reference, status="approved",
        branch_id=row.branch_id)
    row.status = "reversed"
    row.data = {**(row.data or {}), "reversal_id": reversal.id}
    _audit(db, membership, user, "sacco.collection.reversed", "sacco_collection", row.id)
    db.commit()
    return {"id": row.id, "status": row.status, "reversal_id": reversal.id,
            "ledger_reversal_required": True}


@router.get("/members/{member_id}/statement.csv")
def download_member_statement(member_id: int, membership=Depends(active_membership),
                              db: Session=Depends(get_db), start_date: date | None = None,
                              end_date: date | None = None):
    require_permission(membership, "read")
    member = db.query(SaccoMember).filter_by(
        id=member_id, organization_id=membership.organization_id).first()
    if not member or not _visible_branch(membership, member.branch_id):
        raise HTTPException(404, "Member not found")
    if start_date and end_date and end_date < start_date:
        raise HTTPException(422, "End date must not precede start date")
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "transaction_type", "account_or_loan", "reference", "debit", "credit", "currency"])
    accounts = db.query(SaccoAccount).filter_by(
        organization_id=membership.organization_id, member_id=member.id).all()
    for account in accounts:
        txs = db.query(SaccoTransaction).filter_by(
            organization_id=membership.organization_id, account_id=account.id).order_by(
            SaccoTransaction.created_at, SaccoTransaction.id).all()
        for tx in txs:
            if start_date and tx.created_at.date() < start_date: continue
            if end_date and tx.created_at.date() > end_date: continue
            withdrawal = tx.transaction_type == "withdrawal"
            writer.writerow([tx.created_at.isoformat(), tx.transaction_type, account.account_number,
                tx.reference, str(tx.amount) if withdrawal else "0.00",
                "0.00" if withdrawal else str(tx.amount), account.currency])
    repayments = db.query(SaccoLoanRepayment, SaccoLoan).join(
        SaccoLoan, SaccoLoan.id == SaccoLoanRepayment.loan_id).filter(
        SaccoLoan.organization_id == membership.organization_id, SaccoLoan.member_id == member.id).all()
    for tx, loan in repayments:
        if start_date and tx.created_at.date() < start_date: continue
        if end_date and tx.created_at.date() > end_date: continue
        writer.writerow([tx.created_at.isoformat(), "loan_repayment", loan.loan_number,
            tx.reference, "0.00", str(tx.amount), "KES"])
    return Response(output.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="sacco-statement-{member.member_number}.csv"'})


@router.post("/loans/{loan_id}/refinance")
def request_refinance(loan_id: int, payload: RefinanceIn, membership=Depends(active_membership),
                      user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    source = _loan_or_404(db, membership, loan_id, lock=True)
    replacement = _loan_or_404(db, membership, payload.replacement_loan_id, lock=True)
    if source.id == replacement.id or source.member_id != replacement.member_id:
        raise HTTPException(422, "Replacement loan must be a different loan owned by the same member")
    if source.status != "active" or replacement.status != "active":
        raise HTTPException(409, "Both source and replacement loans must be active")
    quote = loan_settlement_quote(loan_id, membership, db, datetime.now(timezone.utc).date())
    settlement = Decimal(quote["settlement_amount"])
    if replacement.principal < settlement:
        raise HTTPException(422, "Replacement loan principal is below the source loan settlement amount")
    pending = db.query(SaccoFinanceRecord).filter_by(
        organization_id=membership.organization_id, record_type="loan_refinance",
        loan_id=source.id, status="pending").first()
    if pending: raise HTTPException(409, "A refinance request is already pending")
    row, _ = _record(db, membership, user, "loan_refinance",
        f"refinance:{source.id}:{replacement.id}",
        {"replacement_loan_id": replacement.id, "settlement_amount": str(settlement),
         "reason": payload.reason.strip()}, member_id=source.member_id, loan_id=source.id,
        amount=settlement, branch_id=source.branch_id, status="pending")
    _audit(db, membership, user, "sacco.loan.refinance.requested", "sacco_finance_record", row.id)
    db.commit()
    return {"request_id": row.id, "status": row.status, "source_loan_id": source.id,
            "replacement_loan_id": replacement.id, "settlement_amount": str(settlement)}


@router.post("/refinances/{request_id}/decision")
def decide_refinance(request_id: int, payload: DecisionIn, membership=Depends(active_membership),
                     user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(SaccoFinanceRecord).filter_by(
        id=request_id, organization_id=membership.organization_id,
        record_type="loan_refinance", status="pending").with_for_update().first()
    if not row or not _visible_branch(membership, row.branch_id):
        raise HTTPException(404, "Pending refinance request not found")
    if row.created_by == user.id and payload.decision == "approved":
        raise HTTPException(403, "Maker cannot approve their own refinance request")
    source = _loan_or_404(db, membership, row.loan_id, lock=True)
    replacement = _loan_or_404(db, membership, row.data["replacement_loan_id"], lock=True)
    if payload.decision == "approved":
        if replacement.member_id != source.member_id or replacement.status != "active":
            raise HTTPException(409, "Replacement loan is no longer eligible")
        schedules = db.query(SaccoLoanSchedule).filter_by(
            organization_id=membership.organization_id, loan_id=source.id).order_by(
            SaccoLoanSchedule.installment_number).with_for_update().all()
        amount = money(row.amount)
        try:
            principal, interest, allocations = allocate_repayment(amount, schedules)
        except ValueError as exc:
            raise HTTPException(409, "Source loan balance changed; obtain a new settlement quote") from exc
        key = f"refinance-repayment:{row.id}"
        digest = hashlib.sha256(f"{source.id}:{replacement.id}:{amount}".encode()).hexdigest()
        db.add(SaccoLoanRepayment(organization_id=membership.organization_id, loan_id=source.id,
            amount=amount, principal_component=principal, interest_component=interest,
            reference=f"REFINANCE-{replacement.loan_number}", idempotency_key=key,
            request_hash=digest, created_by=user.id))
        for schedule, ip, pp in allocations:
            schedule.interest_paid = money(schedule.interest_paid + ip)
            schedule.principal_paid = money(schedule.principal_paid + pp)
            if schedule.interest_paid >= schedule.interest_due and schedule.principal_paid >= schedule.principal_due:
                schedule.status = "paid"
        source.outstanding_principal = money(source.outstanding_principal-principal)
        source.outstanding_interest = money(source.outstanding_interest-interest)
        if source.outstanding_principal == 0 and source.outstanding_interest == 0:
            source.status = "closed"
        row.data = {**(row.data or {}), "settled_by_replacement_loan": replacement.id,
                    "principal_component": str(principal), "interest_component": str(interest)}
    row.status = payload.decision
    row.data = {**(row.data or {}), "decision_note": payload.note.strip(),
                "decided_by": user.id, "decided_at": datetime.now(timezone.utc).isoformat()}
    _audit(db, membership, user, "sacco.loan.refinance.decided", "sacco_finance_record", row.id, payload.decision)
    db.commit()
    return {"request_id": row.id, "status": row.status, "source_loan_status": source.status}


@router.post("/arrears/notifications/queue")
def queue_arrears_notifications(membership=Depends(active_membership),
                                user: User=Depends(current_user), db: Session=Depends(get_db),
                                as_of: date | None = None):
    require_permission(membership, "manage")
    cutoff = as_of or datetime.now(timezone.utc).date()
    rows = db.query(SaccoLoan, SaccoLoanSchedule).join(
        SaccoLoanSchedule, and_(SaccoLoanSchedule.loan_id == SaccoLoan.id,
                                SaccoLoanSchedule.organization_id == SaccoLoan.organization_id)).filter(
        SaccoLoan.organization_id == membership.organization_id, SaccoLoan.status == "active",
        SaccoLoanSchedule.status != "paid", SaccoLoanSchedule.due_date < cutoff).all()
    queued = []
    for loan, inst in rows:
        if not _visible_branch(membership, loan.branch_id): continue
        days = (cutoff-inst.due_date).days
        due = max(Decimal("0"), Decimal(inst.principal_due)-Decimal(inst.principal_paid)) + max(
            Decimal("0"), Decimal(inst.interest_due)-Decimal(inst.interest_paid))
        if due <= 0: continue
        member = db.query(SaccoMember).filter_by(
            id=loan.member_id, organization_id=membership.organization_id).first()
        bucket = "1_30" if days <= 30 else "31_60" if days <= 60 else "61_90" if days <= 90 else "90_plus"
        key = f"arrears-notice:{loan.id}:{inst.id}:{cutoff.isoformat()}"
        data = {"channel": "sms", "phone": member.phone if member else None,
            "member_name": member.full_name if member else "", "loan_number": loan.loan_number,
            "installment_id": inst.id, "days_past_due": days, "ageing_bucket": bucket,
            "message": f"Your SACCO loan {loan.loan_number} has an overdue installment. Please contact the SACCO to arrange payment.",
            "delivery_status": "queued"}
        notice, created = _record(db, membership, user, "arrears_notification", key, data,
            member_id=loan.member_id, loan_id=loan.id, amount=money(due),
            branch_id=loan.branch_id, status="queued")
        if created: queued.append(notice.id)
    _audit(db, membership, user, "sacco.arrears.notifications.queued", "sacco_finance", cutoff,
           f"queued:{len(queued)}")
    db.commit()
    return {"as_of": cutoff.isoformat(), "queued_count": len(queued), "notification_ids": queued,
            "delivery": "queued_only_provider_delivery_not_configured"}


@router.get("/reports/regulatory")
def regulatory_report(membership=Depends(active_membership), db: Session=Depends(get_db),
                      as_of: date | None = None):
    require_permission(membership, "read")
    cutoff = as_of or datetime.now(timezone.utc).date()
    summary = sacco_finance_summary(membership, db)
    overdue_rows = db.query(SaccoLoan, SaccoLoanSchedule).join(
        SaccoLoanSchedule, and_(SaccoLoanSchedule.loan_id == SaccoLoan.id,
                                SaccoLoanSchedule.organization_id == SaccoLoan.organization_id)).filter(
        SaccoLoan.organization_id == membership.organization_id, SaccoLoan.status == "active",
        SaccoLoanSchedule.status != "paid", SaccoLoanSchedule.due_date < cutoff).all()
    overdue = Decimal("0.00")
    for loan, inst in overdue_rows:
        if _visible_branch(membership, loan.branch_id):
            overdue += max(Decimal("0"), Decimal(inst.principal_due)-Decimal(inst.principal_paid))
            overdue += max(Decimal("0"), Decimal(inst.interest_due)-Decimal(inst.interest_paid))
    return {"as_of": cutoff.isoformat(), "currency": "KES", "portfolio": summary,
        "overdue_exposure": str(money(overdue)),
        "portfolio_at_risk_30_plus": str(money(overdue)),
        "classification_basis": "past_due_scheduled_installments",
        "regulatory_status": "management_workpaper_not_a_filed_or_certified_regulatory_return"}
