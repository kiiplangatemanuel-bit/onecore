"""Automatic POS-to-general-ledger posting.

POS source records remain operationally committed if ledger mappings are absent;
their durable bridge links stay pending and can be posted after mapping setup.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import (
    AccountingAccount, AccountingJournal, AccountingJournalLine,
    AccountingFiscalPeriod, AuditEvent, Organization, POSAccountingMapping, POSAccountingLink,
    POSSale, POSSaleLine, POSPayment, POSReturn, POSReturnLine, POSRefund,
)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, branch_scope_ids

router = APIRouter(prefix="/api/v1/accounting", tags=["POS accounting"])
CENT = Decimal("0.01")


def _money(value):
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


class POSAccountingMappingIn(BaseModel):
    cash_account_id: int = Field(gt=0)
    card_clearing_account_id: int = Field(gt=0)
    bank_clearing_account_id: int = Field(gt=0)
    credit_receivable_account_id: int = Field(gt=0)
    sales_revenue_account_id: int = Field(gt=0)
    sales_discount_account_id: int = Field(gt=0)
    output_tax_account_id: int | None = Field(default=None, gt=0)
    sales_returns_account_id: int = Field(gt=0)


def _mapping_dict(mapping):
    if not mapping:
        return None
    return {key: getattr(mapping, key) for key in (
        "cash_account_id", "card_clearing_account_id", "bank_clearing_account_id",
        "credit_receivable_account_id", "sales_revenue_account_id",
        "sales_discount_account_id", "output_tax_account_id", "sales_returns_account_id"
    )}


def _account(db, org_id, account_id):
    if account_id is None:
        return None
    return db.query(AccountingAccount).filter_by(
        id=account_id, organization_id=org_id, is_active=True
    ).first()


def _mapping_error(db, org_id, values):
    expected = {
        "cash_account_id": {"asset"},
        "card_clearing_account_id": {"asset"},
        "bank_clearing_account_id": {"asset"},
        "credit_receivable_account_id": {"asset"},
        "sales_revenue_account_id": {"revenue"},
        "sales_discount_account_id": {"revenue", "expense"},
        "output_tax_account_id": {"liability"},
        "sales_returns_account_id": {"revenue", "expense"},
    }
    for field, account_id in values.items():
        if account_id is None:
            continue
        account = _account(db, org_id, account_id)
        if not account:
            return f"Mapped ledger account {account_id} is missing, inactive or belongs to another organization"
        if account.account_type not in expected[field]:
            return f"Mapped account {account_id} for {field} must be one of: {', '.join(sorted(expected[field]))}"
    return ""


def _line(lines, account_id, debit=0, credit=0, description=""):
    debit, credit = _money(debit), _money(credit)
    if debit == 0 and credit == 0:
        return
    if debit < 0 or credit < 0 or (debit and credit):
        raise ValueError("Invalid POS journal line")
    lines.append((account_id, debit, credit, description))


def _source_lines(db, org_id, source_type, source_id, mapping):
    lines = []
    if source_type == "sale":
        sale = db.query(POSSale).filter_by(id=source_id, organization_id=org_id, status="posted").first()
        if not sale:
            return None, None, "POS sale is missing or not posted"
        payments = db.query(POSPayment).filter_by(
            organization_id=org_id, sale_id=sale.id
        ).all()
        tender_fields = {
            "cash": "cash_account_id", "card": "card_clearing_account_id",
            "bank": "bank_clearing_account_id", "credit": "credit_receivable_account_id",
        }
        debit_by_account = {}
        for payment in payments:
            if payment.status == "unsettled" and payment.method != "credit":
                continue
            key = tender_fields.get(payment.method)
            if not key:
                return None, None, f"Unsupported POS tender method: {payment.method}"
            account_id = mapping[key]
            debit_by_account[account_id] = debit_by_account.get(account_id, Decimal("0")) + _money(payment.amount)
        for account_id, amount in debit_by_account.items():
            _line(lines, account_id, debit=amount, description="POS sale tender")
        _line(lines, mapping["sales_discount_account_id"],
              debit=sale.discount_amount, description="POS sales discounts")
        _line(lines, mapping["sales_revenue_account_id"], credit=sale.subtotal_amount,
              description="POS gross sales revenue")
        if _money(sale.tax_amount):
            if not mapping["output_tax_account_id"]:
                return None, None, "Output tax account is required for taxable POS sales"
            _line(lines, mapping["output_tax_account_id"], credit=sale.tax_amount,
                  description="POS output tax liability")
        return sale, lines, ""
    if source_type == "return":
        result = db.query(POSReturn).filter_by(id=source_id, organization_id=org_id).first()
        if not result:
            return None, None, "POS return is missing"
        sale = db.query(POSSale).filter_by(id=result.sale_id, organization_id=org_id).first()
        if not sale:
            return None, None, "Original POS sale is missing"
        returned_lines = db.query(POSReturnLine).filter_by(
            organization_id=org_id, return_id=result.id
        ).all()
        returned_tax = _money(sum((Decimal(str(row.tax_amount)) for row in returned_lines), Decimal("0")))
        returned_discount = _money(sum((Decimal(str(row.discount_amount)) for row in returned_lines), Decimal("0")))
        return_base = _money(Decimal(str(result.refund_total)) - returned_tax)
        gross_return = _money(return_base + returned_discount)
        _line(lines, mapping["sales_returns_account_id"], debit=gross_return,
              description="POS gross sales returns")
        _line(lines, mapping["sales_discount_account_id"], credit=returned_discount,
              description="Reversal of original POS discount")
        if returned_tax:
            if not mapping["output_tax_account_id"]:
                return None, None, "Output tax account is required for taxable POS returns"
            _line(lines, mapping["output_tax_account_id"], debit=returned_tax,
                  description="Reversal of POS output tax")
        refunds = db.query(POSRefund).filter_by(
            organization_id=org_id, return_id=result.id
        ).all()
        tender_fields = {
            "cash": "cash_account_id", "card": "card_clearing_account_id",
            "bank": "bank_clearing_account_id",
        }
        credit_by_account = {}
        for refund in refunds:
            key = tender_fields.get(refund.method)
            if not key:
                return None, None, f"Unsupported POS refund method: {refund.method}"
            account_id = mapping[key]
            credit_by_account[account_id] = credit_by_account.get(account_id, Decimal("0")) + _money(refund.amount)
        for account_id, amount in credit_by_account.items():
            _line(lines, account_id, credit=amount, description="POS refund payable/clearing")
        return result, lines, ""
    return None, None, "Unsupported POS source type"


def post_pos_source(db: Session, organization_id: int, branch_id: str,
                    source_type: str, source_id: int, actor_user_id: int):
    """Create exactly one posted journal for a POS sale or return; caller owns transaction."""
    link = db.query(POSAccountingLink).filter_by(
        organization_id=organization_id, source_type=source_type, source_id=source_id
    ).with_for_update().first()
    if link and link.status == "posted":
        return link
    if not link:
        link = POSAccountingLink(
            organization_id=organization_id, branch_id=branch_id,
            source_type=source_type, source_id=source_id, status="pending"
        )
        db.add(link)
        db.flush()
    mapping = db.query(POSAccountingMapping).filter_by(organization_id=organization_id).first()
    if not mapping:
        link.status = "pending"
        link.failure_reason = "POS accounting mapping has not been configured"
        return link
    if source_type == "sale":
        sale_currency = db.query(POSSale.currency).filter_by(
            id=source_id, organization_id=organization_id
        ).scalar()
        organization_currency = db.query(Organization.currency).filter_by(id=organization_id).scalar()
        if sale_currency and organization_currency and sale_currency != organization_currency:
            link.status = "pending"
            link.failure_reason = (
                f"POS currency {sale_currency} differs from accounting base currency {organization_currency}"
            )
            return link
    accounts = _mapping_dict(mapping)
    mapping_error = _mapping_error(db, organization_id, accounts)
    if mapping_error:
        link.status = "pending"
        link.failure_reason = mapping_error
        return link
    source, lines, error = _source_lines(db, organization_id, source_type, source_id, accounts)
    if error:
        link.status = "pending"
        link.failure_reason = error
        return link
    if not lines:
        link.status = "pending"
        link.failure_reason = "POS source produced no journal lines"
        return link
    debit = _money(sum((row[1] for row in lines), Decimal("0")))
    credit = _money(sum((row[2] for row in lines), Decimal("0")))
    if debit <= 0 or debit != credit:
        link.status = "pending"
        link.failure_reason = f"POS journal is not balanced (debits {debit}, credits {credit})"
        return link
    created_at = source.created_at or datetime.now(timezone.utc)
    entry_date = created_at.date()
    entry_datetime = datetime.combine(entry_date, datetime.min.time(), tzinfo=timezone.utc)
    closed_period = db.query(AccountingFiscalPeriod).filter(
        AccountingFiscalPeriod.organization_id == organization_id,
        AccountingFiscalPeriod.status == "closed",
        AccountingFiscalPeriod.start_date <= entry_datetime,
        AccountingFiscalPeriod.end_date >= entry_datetime,
    ).first()
    if closed_period:
        link.status = "pending"
        link.failure_reason = f"Source date {entry_date} falls in closed fiscal period {closed_period.code}"
        return link
    prefix = "S" if source_type == "sale" else "R"
    journal = AccountingJournal(
        organization_id=organization_id, branch_id=branch_id,
        journal_number=f"POS-{prefix}-{source_id}", reference=f"POS-{source_type.upper()}:{source_id}",
        memo=f"Automatic POS {source_type} posting #{source_id}",
        status="posted", entry_date=entry_datetime,
        created_by=actor_user_id, posted_by=actor_user_id, posted_at=datetime.now(timezone.utc),
    )
    db.add(journal)
    db.flush()
    for account_id, debit_amount, credit_amount, description in lines:
        db.add(AccountingJournalLine(
            organization_id=organization_id, journal_id=journal.id,
            account_id=account_id, branch_id=branch_id,
            description=description, debit=debit_amount, credit=credit_amount,
        ))
    link.journal_id = journal.id
    link.status = "posted"
    link.failure_reason = ""
    link.posted_at = datetime.now(timezone.utc)
    db.add(AuditEvent(
        organization_id=organization_id, actor_user_id=actor_user_id,
        action=f"pos.accounting.{source_type}.posted", resource_type="accounting_journal",
        resource_id=str(journal.id),
        detail=f"source_type={source_type};source_id={source_id};debits={debit};credits={credit}",
    ))
    db.flush()
    return link


@router.get("/pos-mapping")
def get_pos_accounting_mapping(membership=Depends(active_membership),
                               db: Session = Depends(get_db)):
    require_permission(membership, "read")
    mapping = db.query(POSAccountingMapping).filter_by(
        organization_id=membership.organization_id
    ).first()
    return _mapping_dict(mapping)


@router.put("/pos-mapping")
def put_pos_accounting_mapping(payload: POSAccountingMappingIn,
                               membership=Depends(active_membership),
                               user=Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    mapping_error = _mapping_error(db, membership.organization_id, payload.model_dump())
    if mapping_error:
        raise HTTPException(422, mapping_error)
    mapping = db.query(POSAccountingMapping).filter_by(
        organization_id=membership.organization_id
    ).with_for_update().first()
    if mapping is None:
        mapping = POSAccountingMapping(organization_id=membership.organization_id,
                                       updated_by=user.id, **payload.model_dump())
        db.add(mapping)
    else:
        for key, value in payload.model_dump().items():
            setattr(mapping, key, value)
        mapping.updated_by = user.id
    db.add(AuditEvent(
        organization_id=membership.organization_id, actor_user_id=user.id,
        action="pos.accounting.mapping.updated", resource_type="pos_accounting_mapping",
        resource_id=str(membership.organization_id), detail="POS ledger account mappings updated",
    ))
    db.commit()
    return _mapping_dict(mapping)


@router.get("/pos-integrations")
def list_pos_accounting_integrations(status: str | None = None,
                                     membership=Depends(active_membership),
                                     db: Session = Depends(get_db)):
    require_permission(membership, "read")
    query = db.query(POSAccountingLink).filter_by(organization_id=membership.organization_id)
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        query = query.filter(POSAccountingLink.branch_id.in_(allowed))
    if status:
        if status not in {"pending", "posted"}:
            raise HTTPException(422, "Status must be pending or posted")
        query = query.filter_by(status=status)
    rows = query.order_by(POSAccountingLink.id.desc()).limit(500).all()
    return [{"id": row.id, "source_type": row.source_type, "source_id": row.source_id,
             "branch_id": row.branch_id, "status": row.status, "journal_id": row.journal_id,
             "failure_reason": row.failure_reason, "posted_at": row.posted_at.isoformat() if row.posted_at else None}
            for row in rows]


@router.post("/pos-integrations/post-pending")
def post_pending_pos_accounting(membership=Depends(active_membership),
                                user=Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    query = db.query(POSAccountingLink).filter_by(
        organization_id=membership.organization_id, status="pending"
    )
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        query = query.filter(POSAccountingLink.branch_id.in_(allowed))
    links = query.order_by(POSAccountingLink.id).limit(500).with_for_update().all()
    results = []
    for row in links:
        link = post_pos_source(db, membership.organization_id, row.branch_id,
                               row.source_type, row.source_id, user.id)
        results.append({"source_type": link.source_type, "source_id": link.source_id,
                        "status": link.status, "journal_id": link.journal_id,
                        "failure_reason": link.failure_reason})
    db.commit()
    return {"processed": len(results), "posted": sum(1 for item in results if item["status"] == "posted"),
            "pending": sum(1 for item in results if item["status"] == "pending"), "results": results}
