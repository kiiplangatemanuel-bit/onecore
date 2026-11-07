from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import (
    AccountingAccount, AccountingCreditNote, AccountingInvoice, AccountingInvoiceLine,
    AccountingJournal, AccountingJournalLine, AccountingProcurementLink, AccountingRefund, AccountingFiscalPeriod,
    AccountingInvoiceApproval, AuditEvent, Organization, ProcurementSupplierInvoice,
    ProcurementSupplierInvoiceLine, ProcurementPurchaseOrder, ProcurementPurchaseOrderLine,
)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, branch_scope_ids, can_access_branch
from app.core.models import ProcurementSupplier

# The existing ledger helpers centralize period validation and balanced journal creation.
from app.api.routes import (_accounting_make_journal, _accounting_assert_period_open, _procurement_branch_check, _accounting_period_close_check)

router = APIRouter(prefix="/api/v1/accounting", tags=["accounting-completion"])
CENT = Decimal("0.01")


class ProcurementAPLineMapping(BaseModel):
    supplier_invoice_line_id: int = Field(gt=0)
    expense_account_id: int = Field(gt=0)


class ProcurementAPIntegrationIn(BaseModel):
    due_date: date
    payable_control_account_id: int = Field(gt=0)
    tax_account_id: int | None = Field(default=None, gt=0)
    lines: list[ProcurementAPLineMapping] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_source_lines(self):
        ids = [x.supplier_invoice_line_id for x in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Each matched supplier invoice line must be mapped exactly once")
        return self


class AccountingRefundIn(BaseModel):
    payment_account_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0, le=Decimal("9999999999999999"), multiple_of=CENT)
    refund_date: date
    reference: str = Field(default="", max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=100)


def _audit(db, user_id, organization_id, action, resource_type, resource_id, detail=""):
    db.add(AuditEvent(actor_user_id=user_id, organization_id=organization_id,
                      action=action, resource_type=resource_type,
                      resource_id=str(resource_id), detail=detail))


def _visible_branch(membership, branch_id):
    if branch_id is not None and not can_access_branch(membership, branch_id):
        raise HTTPException(404, "Accounting record not found")


@router.get("/cash-flow")
def accounting_cash_flow(
    start_date: date,
    end_date: date,
    cash_account_ids: list[int] = Query(..., min_length=1),
    membership=Depends(active_membership),
    db: Session = Depends(get_db),
):
    """Ledger-derived cash movement report using selected cash/bank accounts."""
    require_permission(membership, "read")
    if end_date < start_date:
        raise HTTPException(422, "End date must not precede start date")
    if len(cash_account_ids) != len(set(cash_account_ids)):
        raise HTTPException(422, "Cash account IDs must be unique")
    accounts = db.query(AccountingAccount).filter(
        AccountingAccount.organization_id == membership.organization_id,
        AccountingAccount.id.in_(cash_account_ids),
    ).all()
    by_id = {x.id: x for x in accounts}
    if set(by_id) != set(cash_account_ids):
        raise HTTPException(404, "One or more cash accounts were not found")
    if any(x.account_type != "asset" for x in accounts):
        raise HTTPException(422, "Cash-flow accounts must be asset accounts")

    start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(end_date, time.max, tzinfo=timezone.utc)
    q = db.query(AccountingJournalLine, AccountingJournal, AccountingAccount).join(
        AccountingJournal, AccountingJournal.id == AccountingJournalLine.journal_id
    ).join(AccountingAccount, AccountingAccount.id == AccountingJournalLine.account_id).filter(
        AccountingJournalLine.organization_id == membership.organization_id,
        AccountingJournal.organization_id == membership.organization_id,
        AccountingAccount.organization_id == membership.organization_id,
        AccountingJournal.status == "posted",
        AccountingJournal.entry_date >= start,
        AccountingJournal.entry_date <= end,
    )
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            return {"period": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
                    "cash_accounts": cash_account_ids, "opening_balance": "0.00",
                    "operating": "0.00", "investing": "0.00", "financing": "0.00",
                    "net_change": "0.00", "closing_balance": "0.00", "transactions": 0}
        q = q.filter((AccountingJournalLine.branch_id.is_(None)) |
                     (AccountingJournalLine.branch_id.in_(allowed)))
    rows = q.all()
    grouped = {}
    for line, journal, account in rows:
        grouped.setdefault(journal.id, []).append((line, journal, account))

    totals = {"operating": Decimal("0.00"), "investing": Decimal("0.00"),
              "financing": Decimal("0.00"), "unclassified": Decimal("0.00")}
    cash_net = Decimal("0.00")
    for journal_rows in grouped.values():
        cash_delta = sum((Decimal(line.debit) - Decimal(line.credit)
                          for line, _, account in journal_rows if account.id in by_id), Decimal("0.00"))
        if not cash_delta:
            continue
        cash_net += cash_delta
        weights = {"operating": Decimal("0"), "investing": Decimal("0"), "financing": Decimal("0")}
        for line, _, account in journal_rows:
            if account.id in by_id:
                continue
            magnitude = abs(Decimal(line.debit) - Decimal(line.credit))
            if account.account_type in ("revenue", "expense"):
                weights["operating"] += magnitude
            elif account.account_type == "asset":
                weights["investing"] += magnitude
            elif account.account_type in ("liability", "equity"):
                weights["financing"] += magnitude
        weight_total = sum(weights.values(), Decimal("0"))
        if not weight_total:
            totals["unclassified"] += cash_delta
            continue
        # Allocate a multi-account journal proportionally; the final bucket absorbs rounding.
        active = [k for k, v in weights.items() if v]
        remaining = cash_delta
        for key in active[:-1]:
            share = (cash_delta * weights[key] / weight_total).quantize(CENT, rounding=ROUND_HALF_UP)
            totals[key] += share
            remaining -= share
        totals[active[-1]] += remaining

    opening_q = db.query(func.coalesce(func.sum(AccountingJournalLine.debit - AccountingJournalLine.credit), 0)).join(
        AccountingJournal, AccountingJournal.id == AccountingJournalLine.journal_id
    ).filter(
        AccountingJournalLine.organization_id == membership.organization_id,
        AccountingJournalLine.account_id.in_(cash_account_ids),
        AccountingJournal.organization_id == membership.organization_id,
        AccountingJournal.status == "posted",
        AccountingJournal.entry_date < start,
    )
    if allowed is not None:
        opening_q = opening_q.filter((AccountingJournalLine.branch_id.is_(None)) |
                                     (AccountingJournalLine.branch_id.in_(allowed)))
    opening = Decimal(opening_q.scalar() or 0)
    net = sum(totals.values(), Decimal("0.00"))
    return {
        "period": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "cash_accounts": [{"id": x.id, "code": x.code, "name": x.name} for x in accounts],
        "opening_balance": str(opening),
        "operating": str(totals["operating"]),
        "investing": str(totals["investing"]),
        "financing": str(totals["financing"]),
        "unclassified": str(totals["unclassified"]),
        "net_change": str(net),
        "closing_balance": str(opening + net),
        "transactions": len(grouped),
        "method": "ledger-derived; journal counterpart account types; multi-category journals allocated proportionally",
    }


@router.get("/statutory-tax-summary")
def accounting_statutory_tax_summary(
    start_date: date,
    end_date: date,
    tax_account_ids: list[int] = Query(..., min_length=1),
    membership=Depends(active_membership),
    db: Session = Depends(get_db),
):
    """Prepare a tax-ledger workpaper; does not determine tax law or submit returns."""
    require_permission(membership, "read")
    if end_date < start_date:
        raise HTTPException(422, "End date must not precede start date")
    if len(tax_account_ids) != len(set(tax_account_ids)):
        raise HTTPException(422, "Tax account IDs must be unique")
    accounts = db.query(AccountingAccount).filter(
        AccountingAccount.organization_id == membership.organization_id,
        AccountingAccount.id.in_(tax_account_ids),
    ).all()
    by_id = {x.id: x for x in accounts}
    if set(by_id) != set(tax_account_ids):
        raise HTTPException(404, "One or more tax accounts were not found")
    if any(x.account_type not in ("asset", "liability") for x in accounts):
        raise HTTPException(422, "Tax accounts must be asset (input tax) or liability (output tax) accounts")
    start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(end_date, time.max, tzinfo=timezone.utc)
    q = db.query(AccountingJournalLine).join(
        AccountingJournal, AccountingJournal.id == AccountingJournalLine.journal_id
    ).filter(
        AccountingJournalLine.organization_id == membership.organization_id,
        AccountingJournal.organization_id == membership.organization_id,
        AccountingJournal.status == "posted",
        AccountingJournal.entry_date >= start,
        AccountingJournal.entry_date <= end,
        AccountingJournalLine.account_id.in_(tax_account_ids),
    )
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            return {"period": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
                    "accounts": [], "output_tax": "0.00", "input_tax": "0.00", "net_tax_payable": "0.00"}
        q = q.filter((AccountingJournalLine.branch_id.is_(None)) |
                     (AccountingJournalLine.branch_id.in_(allowed)))
    totals = {x.id: {"debit": Decimal("0.00"), "credit": Decimal("0.00")} for x in accounts}
    for line in q.all():
        totals[line.account_id]["debit"] += Decimal(line.debit)
        totals[line.account_id]["credit"] += Decimal(line.credit)
    output_tax = Decimal("0.00")
    input_tax = Decimal("0.00")
    result = []
    for account in accounts:
        debit, credit = totals[account.id]["debit"], totals[account.id]["credit"]
        movement = credit - debit if account.account_type == "liability" else debit - credit
        if account.account_type == "liability":
            output_tax += movement
        else:
            input_tax += movement
        result.append({"account_id": account.id, "code": account.code, "name": account.name,
                       "tax_role": "output_tax" if account.account_type == "liability" else "input_tax",
                       "debits": str(debit), "credits": str(credit), "net_movement": str(movement)})
    return {
        "period": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "accounts": result, "output_tax": str(output_tax), "input_tax": str(input_tax),
        "net_tax_payable": str(output_tax - input_tax),
        "basis": "posted general-ledger movements in operator-selected tax accounts",
        "filing_status": "workpaper_only",
        "disclaimer": "Not a KRA/eTIMS filing, tax determination, tax invoice validation, or statutory certification.",
    }


@router.post("/procurement-invoices/{supplier_invoice_id}/integrate", status_code=201)
def integrate_procurement_invoice_to_ap(
    supplier_invoice_id: int,
    payload: ProcurementAPIntegrationIn,
    membership=Depends(active_membership),
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    """Convert a three-way-matched procurement bill into a controlled AP draft."""
    require_permission(membership, "manage")
    source = db.query(ProcurementSupplierInvoice).filter_by(
        id=supplier_invoice_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not source:
        raise HTTPException(404, "Matched procurement invoice not found")
    existing = db.query(AccountingProcurementLink).filter_by(
        organization_id=membership.organization_id, procurement_invoice_id=source.id
    ).first()
    if existing:
        return {"procurement_invoice_id": source.id, "accounting_invoice_id": existing.accounting_invoice_id,
                "status": "already_integrated"}
    if source.status != "matched":
        raise HTTPException(409, "Only a three-way-matched supplier invoice can be integrated")
    if payload.due_date < source.invoice_date.date():
        raise HTTPException(422, "AP due date cannot precede the supplier invoice date")
    order = db.query(ProcurementPurchaseOrder).filter_by(
        id=source.purchase_order_id, organization_id=membership.organization_id,
        supplier_id=source.supplier_id,
    ).first()
    if not order:
        raise HTTPException(409, "Source purchase order is unavailable")
    _procurement_branch_check(db, membership, order.branch_id)
    org = db.query(Organization).filter_by(id=membership.organization_id, is_active=True).first()
    if not org or source.currency != org.currency:
        raise HTTPException(422, "Procurement invoice currency must match the accounting base currency")
    payable = db.query(AccountingAccount).filter_by(
        id=payload.payable_control_account_id, organization_id=membership.organization_id
    ).first()
    if not payable or payable.account_type != "liability":
        raise HTTPException(422, "AP control account must be an organization liability account")
    source_lines = db.query(ProcurementSupplierInvoiceLine).filter_by(
        organization_id=membership.organization_id, invoice_id=source.id
    ).order_by(ProcurementSupplierInvoiceLine.id).all()
    mapping = {x.supplier_invoice_line_id: x.expense_account_id for x in payload.lines}
    if set(mapping) != {x.id for x in source_lines}:
        raise HTTPException(422, "Map every matched procurement invoice line exactly once")
    account_ids = set(mapping.values())
    if payload.tax_account_id:
        account_ids.add(payload.tax_account_id)
    ledger_accounts = {x.id: x for x in db.query(AccountingAccount).filter(
        AccountingAccount.organization_id == membership.organization_id,
        AccountingAccount.id.in_(account_ids),
    ).all()}
    if set(ledger_accounts) != account_ids:
        raise HTTPException(404, "One or more mapped ledger accounts were not found")
    if any(ledger_accounts[x].account_type not in ("expense", "asset") for x in mapping.values()):
        raise HTTPException(422, "Supplier invoice lines must map to expense or asset accounts")
    if source.tax_total and (not payload.tax_account_id or ledger_accounts[payload.tax_account_id].account_type != "asset"):
        raise HTTPException(422, "Input-tax asset account is required for a taxed supplier invoice")
    if not source.tax_total and payload.tax_account_id:
        raise HTTPException(422, "Omit the input-tax account when the supplier invoice has no tax")
    if not source.tax_total and payload.tax_account_id:
        raise HTTPException(422, "Omit tax account when the supplier invoice has no tax")
    subtotal = Decimal(source.subtotal)
    if subtotal <= 0 or Decimal(source.tax_total) < 0:
        raise HTTPException(422, "Matched supplier invoice totals are invalid")
    invoice_number = f"PROC-{source.id}"
    duplicate = db.query(AccountingInvoice).filter_by(
        organization_id=membership.organization_id, invoice_number=invoice_number
    ).first()
    if duplicate:
        raise HTTPException(409, "A ledger invoice with this procurement source already exists without its bridge record")
    ledger_invoice = AccountingInvoice(
        organization_id=membership.organization_id, branch_id=order.branch_id,
        invoice_type="payable", supplier_id=source.supplier_id, invoice_number=invoice_number,
        issue_date=source.invoice_date, due_date=datetime.combine(payload.due_date, time.min, tzinfo=timezone.utc),
        currency=source.currency, control_account_id=payable.id, subtotal=subtotal,
        tax_total=Decimal(source.tax_total), total=subtotal + Decimal(source.tax_total),
        amount_paid=Decimal("0.00"), status="draft", created_by=user.id,
    )
    db.add(ledger_invoice)
    db.flush()
    line_subtotals = [
        (Decimal(line.quantity) * Decimal(line.unit_cost)).quantize(CENT, rounding=ROUND_HALF_UP)
        for line in source_lines
    ]
    taxable_indexes = [i for i, value in enumerate(line_subtotals) if value > 0]
    last_taxable_index = taxable_indexes[-1] if taxable_indexes else -1
    allocated = Decimal("0.00")
    for index, line in enumerate(source_lines):
        line_sub = line_subtotals[index]
        if not source.tax_total or not line_sub:
            tax_amount = Decimal("0.00")
        elif index == last_taxable_index:
            tax_amount = Decimal(source.tax_total) - allocated
        else:
            tax_amount = (Decimal(source.tax_total) * line_sub / subtotal).quantize(CENT, rounding=ROUND_HALF_UP)
            allocated += tax_amount
        tax_rate = ((tax_amount * Decimal("100") / line_sub).quantize(Decimal("0.0001"))
                    if line_sub else Decimal("0.0000"))
        db.add(AccountingInvoiceLine(
            organization_id=membership.organization_id, invoice_id=ledger_invoice.id,
            account_id=mapping[line.id], tax_account_id=payload.tax_account_id,
            description=f"Procurement invoice {source.invoice_number} · PO line {line.purchase_order_line_id}",
            quantity=line.quantity, unit_price=line.unit_cost, subtotal=line_sub,
            tax_rate=tax_rate, tax_amount=tax_amount, total=line_sub + tax_amount,
        ))
    db.add(AccountingProcurementLink(
        organization_id=membership.organization_id, procurement_invoice_id=source.id,
        accounting_invoice_id=ledger_invoice.id, created_by=user.id,
    ))
    source.status = "accounted"
    # Force the same maker-checker approval path as manually entered supplier bills.
    db.add(AccountingInvoiceApproval(
        organization_id=membership.organization_id, invoice_id=ledger_invoice.id,
        submitted_by=user.id, status="pending",
    ))
    _audit(db, user.id, membership.organization_id, "accounting.procurement_invoice.integrated",
           "accounting_invoice", ledger_invoice.id, f"procurement_invoice_id={source.id}")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Procurement invoice integration conflicted with another request")
    return {"procurement_invoice_id": source.id, "accounting_invoice_id": ledger_invoice.id,
            "invoice_number": ledger_invoice.invoice_number, "status": "draft",
            "approval_status": "pending", "total": str(ledger_invoice.total)}


@router.post("/credit-notes/{credit_note_id}/refund", status_code=201)
def refund_accounting_credit_note(
    credit_note_id: int,
    payload: AccountingRefundIn,
    membership=Depends(active_membership),
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    """Record a cash refund against a posted AR/AP credit note and post its journal."""
    require_permission(membership, "manage")
    note = db.query(AccountingCreditNote).filter_by(
        id=credit_note_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not note or note.status != "posted":
        raise HTTPException(404, "Posted credit note not found")
    invoice = db.query(AccountingInvoice).filter_by(
        id=note.invoice_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not invoice:
        raise HTTPException(404, "Credit note invoice not found")
    _visible_branch(membership, note.branch_id)
    duplicate = db.query(AccountingRefund).filter_by(
        organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
    ).first()
    if duplicate:
        if (duplicate.credit_note_id == note.id and duplicate.amount == payload.amount
                and duplicate.payment_account_id == payload.payment_account_id
                and duplicate.refund_date.date() == payload.refund_date
                and duplicate.reference == payload.reference.strip()):
            return {"id": duplicate.id, "status": "already_applied", "journal_id": duplicate.journal_id}
        raise HTTPException(409, "Refund idempotency key has already been used")
    already_refunded = db.query(func.coalesce(func.sum(AccountingRefund.amount), 0)).filter_by(
        organization_id=membership.organization_id, credit_note_id=note.id
    ).scalar() or Decimal("0.00")
    if payload.amount > Decimal(note.total) - Decimal(already_refunded):
        raise HTTPException(422, "Refund exceeds the remaining credit-note balance")
    if payload.amount > Decimal(invoice.amount_paid):
        raise HTTPException(422, "Refund exceeds cash previously settled against the invoice")
    _accounting_assert_period_open(db, membership.organization_id, payload.refund_date)
    cash = db.query(AccountingAccount).filter_by(
        id=payload.payment_account_id, organization_id=membership.organization_id
    ).first()
    if not cash or cash.account_type != "asset":
        raise HTTPException(422, "Refund cash/bank account must be an organization asset account")
    amount = payload.amount
    if invoice.invoice_type == "receivable":
        lines = [
            {"account_id": invoice.control_account_id, "description": "Customer refund " + note.credit_note_number,
             "debit": amount, "credit": Decimal("0.00")},
            {"account_id": cash.id, "description": "Cash refund " + note.credit_note_number,
             "debit": Decimal("0.00"), "credit": amount},
        ]
    else:
        lines = [
            {"account_id": cash.id, "description": "Supplier refund received " + note.credit_note_number,
             "debit": amount, "credit": Decimal("0.00")},
            {"account_id": invoice.control_account_id, "description": "Settle supplier credit " + note.credit_note_number,
             "debit": Decimal("0.00"), "credit": amount},
        ]
    journal = _accounting_make_journal(
        db, membership, user, payload.refund_date, payload.reference or note.credit_note_number,
        "Credit note refund " + note.credit_note_number, lines, invoice.branch_id,
    )
    refund = AccountingRefund(
        organization_id=membership.organization_id, invoice_id=invoice.id, credit_note_id=note.id,
        payment_account_id=cash.id, journal_id=journal.id, amount=amount,
        refund_date=datetime.combine(payload.refund_date, time.min, tzinfo=timezone.utc),
        reference=payload.reference.strip(), idempotency_key=payload.idempotency_key, created_by=user.id,
    )
    db.add(refund)
    invoice.amount_paid = Decimal(invoice.amount_paid) - amount
    invoice.status = "paid" if invoice.amount_paid == invoice.total else (
        "partially_paid" if invoice.amount_paid > 0 else "posted"
    )
    _audit(db, user.id, membership.organization_id, "accounting.credit_note.refunded",
           "accounting_refund", credit_note_id, str(amount))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Refund conflicts with another request")
    return {"id": refund.id, "credit_note_id": note.id, "invoice_id": invoice.id,
            "direction": "customer_refund" if invoice.invoice_type == "receivable" else "supplier_refund",
            "amount": str(amount), "status": "posted", "journal_id": journal.id}


@router.get("/refunds")
def list_accounting_refunds(
    invoice_id: int | None = None,
    membership=Depends(active_membership),
    db: Session = Depends(get_db),
):
    require_permission(membership, "read")
    q = db.query(AccountingRefund).filter_by(organization_id=membership.organization_id)
    if invoice_id is not None:
        q = q.filter(AccountingRefund.invoice_id == invoice_id)
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            return []
        q = q.join(AccountingInvoice, AccountingInvoice.id == AccountingRefund.invoice_id).filter(
            (AccountingInvoice.branch_id.is_(None)) | (AccountingInvoice.branch_id.in_(allowed))
        )
    rows = q.order_by(AccountingRefund.id.desc()).limit(500).all()
    return [{"id": x.id, "invoice_id": x.invoice_id, "credit_note_id": x.credit_note_id,
             "amount": str(x.amount), "refund_date": x.refund_date.date().isoformat(),
             "reference": x.reference, "journal_id": x.journal_id} for x in rows]



class AccountingYearEndCloseIn(BaseModel):
    retained_earnings_account_id: int = Field(gt=0)
    confirmation_code: str = Field(min_length=2, max_length=40)


def _year_end_close_calculation(db, membership, period, retained_earnings_account_id):
    if branch_scope_ids(membership) is not None:
        raise HTTPException(403, "Year-end close requires organization-wide branch access")
    retained = db.query(AccountingAccount).filter_by(
        id=retained_earnings_account_id, organization_id=membership.organization_id, is_active=True
    ).first()
    if not retained or retained.account_type != "equity":
        raise HTTPException(422, "Retained-earnings account must be an active organization equity account")
    start, end = period.start_date, period.end_date
    q = db.query(AccountingAccount, AccountingJournalLine).join(
        AccountingJournalLine, AccountingJournalLine.account_id == AccountingAccount.id
    ).join(AccountingJournal, AccountingJournal.id == AccountingJournalLine.journal_id).filter(
        AccountingAccount.organization_id == membership.organization_id,
        AccountingJournalLine.organization_id == membership.organization_id,
        AccountingJournal.organization_id == membership.organization_id,
        AccountingJournal.status == "posted",
        AccountingJournal.entry_date >= start,
        AccountingJournal.entry_date <= end,
        AccountingAccount.account_type.in_(("revenue", "expense")),
    )
    balances = {}
    for account, line in q.all():
        row = balances.setdefault(account.id, {
            "account": account, "debit": Decimal("0.00"), "credit": Decimal("0.00")
        })
        row["debit"] += Decimal(line.debit)
        row["credit"] += Decimal(line.credit)
    journal_lines = []
    revenue_total = Decimal("0.00")
    expense_total = Decimal("0.00")
    for item in balances.values():
        account = item["account"]
        if account.account_type == "revenue":
            balance = item["credit"] - item["debit"]
            revenue_total += balance
            if balance > 0:
                journal_lines.append({"account_id": account.id, "description": "Close revenue " + account.code,
                                      "debit": balance, "credit": Decimal("0.00")})
            elif balance < 0:
                journal_lines.append({"account_id": account.id, "description": "Close revenue reversal " + account.code,
                                      "debit": Decimal("0.00"), "credit": -balance})
        else:
            balance = item["debit"] - item["credit"]
            expense_total += balance
            if balance > 0:
                journal_lines.append({"account_id": account.id, "description": "Close expense " + account.code,
                                      "debit": Decimal("0.00"), "credit": balance})
            elif balance < 0:
                journal_lines.append({"account_id": account.id, "description": "Close expense reversal " + account.code,
                                      "debit": -balance, "credit": Decimal("0.00")})
    net_income = revenue_total - expense_total
    if net_income > 0:
        journal_lines.append({"account_id": retained.id, "description": "Transfer net income to retained earnings",
                              "debit": Decimal("0.00"), "credit": net_income})
    elif net_income < 0:
        journal_lines.append({"account_id": retained.id, "description": "Transfer net loss to retained earnings",
                              "debit": -net_income, "credit": Decimal("0.00")})
    return {
        "retained_earnings_account": {"id": retained.id, "code": retained.code, "name": retained.name},
        "revenue": revenue_total, "expenses": expense_total, "net_income": net_income,
        "lines": journal_lines,
    }


@router.get("/fiscal-periods/{period_id}/year-end-close-preview")
def accounting_year_end_close_preview(
    period_id: int,
    retained_earnings_account_id: int = Query(..., gt=0),
    membership=Depends(active_membership),
    db: Session = Depends(get_db),
):
    require_permission(membership, "read")
    period = db.query(AccountingFiscalPeriod).filter_by(
        id=period_id, organization_id=membership.organization_id
    ).first()
    if not period:
        raise HTTPException(404, "Fiscal period not found")
    if period.status != "open":
        raise HTTPException(409, "Year-end preview requires an open fiscal period")
    calculation = _year_end_close_calculation(db, membership, period, retained_earnings_account_id)
    checks = _accounting_period_close_check(db, membership.organization_id, period)
    return {
        "period_id": period.id, "period_code": period.code,
        "start_date": period.start_date.date().isoformat(), "end_date": period.end_date.date().isoformat(),
        "close_checks": checks, "ready_to_close": checks["ready_to_close"],
        "retained_earnings_account": calculation["retained_earnings_account"],
        "revenue": str(calculation["revenue"]), "expenses": str(calculation["expenses"]),
        "net_income": str(calculation["net_income"]),
        "journal_lines": [{"account_id": x["account_id"], "description": x["description"],
                           "debit": str(x["debit"]), "credit": str(x["credit"])}
                          for x in calculation["lines"]],
        "requires_confirmation": period.code,
    }


@router.post("/fiscal-periods/{period_id}/year-end-close")
def post_accounting_year_end_close(
    period_id: int,
    payload: AccountingYearEndCloseIn,
    membership=Depends(active_membership),
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    require_permission(membership, "manage")
    period = db.query(AccountingFiscalPeriod).filter_by(
        id=period_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not period:
        raise HTTPException(404, "Fiscal period not found")
    if period.status != "open":
        raise HTTPException(409, "Fiscal period is already closed")
    if payload.confirmation_code != period.code:
        raise HTTPException(422, "Fiscal period confirmation code does not match")
    checks = _accounting_period_close_check(db, membership.organization_id, period)
    if not checks["ready_to_close"]:
        raise HTTPException(409, detail={
            "message": "Fiscal period has unresolved close blockers",
            "period_id": period.id, "blockers": checks["blockers"], "checks": checks["checks"],
        })
    reference = "YEAR-END-CLOSE-" + str(period.id)
    duplicate = db.query(AccountingJournal).filter_by(
        organization_id=membership.organization_id, reference=reference, status="posted"
    ).first()
    if duplicate:
        raise HTTPException(409, "A year-end closing journal already exists for this fiscal period")
    calculation = _year_end_close_calculation(db, membership, period, payload.retained_earnings_account_id)
    journal = None
    if calculation["lines"]:
        journal = _accounting_make_journal(
            db, membership, user, period.end_date.date(), reference,
            "Fiscal year-end close " + period.code, calculation["lines"], None,
        )
    period.status = "closed"
    period.closed_by = user.id
    period.closed_at = datetime.now(timezone.utc)
    _audit(db, user.id, membership.organization_id, "accounting.period.year_end_closed",
           "accounting_period", period.id, reference)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Year-end close conflicted with another posting")
    return {
        "period_id": period.id, "period_code": period.code, "status": period.status,
        "journal_id": journal.id if journal else None,
        "journal_number": journal.journal_number if journal else None,
        "net_income": str(calculation["net_income"]), "closed_at": period.closed_at.isoformat(),
    }
