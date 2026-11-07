from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import (
    AccountingInvoice, AccountingInvoicePayment, CRMContact, ProcurementSupplier,
)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, branch_scope_ids

router = APIRouter(prefix="/api/v1/accounting", tags=["accounting-statements"])


def _midnight(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


@router.get("/statements/{counterparty_type}/{counterparty_id}")
def counterparty_statement(
    counterparty_type: str,
    counterparty_id: int,
    start_date: date = Query(...),
    end_date: date = Query(...),
    membership=Depends(active_membership),
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    """Build a tenant/branch-scoped AR or AP statement from posted invoices and payments."""
    require_permission(membership, "read")
    if counterparty_type not in {"customer", "supplier"}:
        raise HTTPException(422, "counterparty_type must be customer or supplier")
    if start_date > end_date:
        raise HTTPException(422, "start_date must not be after end_date")

    if counterparty_type == "customer":
        counterparty = db.query(CRMContact).filter_by(
            id=counterparty_id, organization_id=membership.organization_id
        ).first()
        invoice_type = "receivable"
    else:
        counterparty = db.query(ProcurementSupplier).filter_by(
            id=counterparty_id, organization_id=membership.organization_id
        ).first()
        invoice_type = "payable"
    if not counterparty:
        raise HTTPException(404, "Counterparty not found")

    query = db.query(AccountingInvoice).filter(
        AccountingInvoice.organization_id == membership.organization_id,
        AccountingInvoice.invoice_type == invoice_type,
        AccountingInvoice.status.in_(("posted", "partially_paid", "paid")),
    )
    if counterparty_type == "customer":
        query = query.filter(AccountingInvoice.contact_id == counterparty_id)
    else:
        query = query.filter(AccountingInvoice.supplier_id == counterparty_id)

    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            raise HTTPException(403, "No branch access is assigned")
        query = query.filter(AccountingInvoice.branch_id.in_(allowed))

    invoices = query.order_by(AccountingInvoice.issue_date, AccountingInvoice.id).all()
    invoice_ids = [row.id for row in invoices]
    payments = []
    if invoice_ids:
        payments = db.query(AccountingInvoicePayment).filter(
            AccountingInvoicePayment.organization_id == membership.organization_id,
            AccountingInvoicePayment.invoice_id.in_(invoice_ids),
        ).order_by(AccountingInvoicePayment.payment_date, AccountingInvoicePayment.id).all()

    events = []
    for invoice in invoices:
        events.append({
            "date": invoice.issue_date.date(),
            "kind": "invoice",
            "reference": invoice.invoice_number,
            "description": "Invoice",
            "debit": Decimal("0.00"),
            "credit": Decimal("0.00"),
            "amount": Decimal(invoice.total),
            "invoice_id": invoice.id,
            "due_date": invoice.due_date.date().isoformat(),
        })
    for payment in payments:
        invoice = next((row for row in invoices if row.id == payment.invoice_id), None)
        if invoice is None:
            continue
        events.append({
            "date": payment.payment_date.date(),
            "kind": "payment",
            "reference": payment.reference or f"PAY-{payment.id}",
            "description": "Payment",
            "debit": Decimal("0.00"),
            "credit": Decimal("0.00"),
            "amount": -Decimal(payment.amount),
            "invoice_id": invoice.id,
            "due_date": None,
        })

    events.sort(key=lambda item: (item["date"], item["kind"] == "payment", item["reference"], item["invoice_id"]))
    opening = sum((item["amount"] for item in events if item["date"] < start_date), Decimal("0.00"))
    balance = opening
    rows = []
    for item in events:
        if item["date"] < start_date or item["date"] > end_date:
            continue
        balance += item["amount"]
        rows.append({
            "date": item["date"].isoformat(),
            "type": item["kind"],
            "reference": item["reference"],
            "description": item["description"],
            "invoice_id": item["invoice_id"],
            "due_date": item["due_date"],
            "amount": str(abs(item["amount"])),
            "balance": str(balance),
        })

    closing = balance
    name = getattr(counterparty, "full_name", None) or counterparty.name
    return {
        "counterparty": {"type": counterparty_type, "id": counterparty_id, "name": name},
        "currency": invoices[0].currency if invoices else "KES",
        "period": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "opening_balance": str(opening),
        "transactions": rows,
        "closing_balance": str(closing),
        "invoice_count": sum(1 for item in rows if item["type"] == "invoice"),
        "payment_count": sum(1 for item in rows if item["type"] == "payment"),
    }
