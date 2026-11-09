"""Tenant-scoped M-Pesa settlement statement import and reconciliation.

Statement imports are idempotent and never initiate provider payments or mutate
posted accounting journals. A matched line is evidence that a provider statement
contains a previously confirmed callback receipt; exceptions require review.
"""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import AuditEvent, MpesaPaymentIntent, MpesaRefundIntent
from app.core.mpesa_settlement_models import MpesaSettlementBatch, MpesaSettlementLine
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission

router = APIRouter(prefix="/api/v1/integrations/mpesa/settlements", tags=["M-Pesa settlement"])
CENT = Decimal("0.01")


class SettlementEntry(BaseModel):
    receipt_number: str = Field(min_length=4, max_length=40)
    transaction_type: Literal["collection", "payout"]
    transaction_at: datetime
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    account_reference: str = Field(default="", max_length=120)

    @field_validator("receipt_number")
    @classmethod
    def clean_receipt(cls, value):
        value = value.strip()
        if not value or any(ch.isspace() for ch in value):
            raise ValueError("Receipt number must be a non-empty token")
        return value

    @field_validator("transaction_at")
    @classmethod
    def require_timezone(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Transaction timestamps must include a timezone")
        return value


class SettlementImport(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=100)
    source: Literal["daraja_statement", "provider_export"] = "daraja_statement"
    currency: Literal["KES"] = "KES"
    entries: list[SettlementEntry] = Field(min_length=1, max_length=5000)


def _canonical_payload(payload: SettlementImport) -> str:
    data = payload.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _match_entry(db: Session, organization_id: int, entry: SettlementEntry):
    if entry.transaction_type == "collection":
        row = db.query(MpesaPaymentIntent).filter_by(
            organization_id=organization_id,
            mpesa_receipt_number=entry.receipt_number,
            status="success",
        ).one_or_none()
        kind = "collection"
    else:
        row = db.query(MpesaRefundIntent).filter_by(
            organization_id=organization_id,
            mpesa_receipt_number=entry.receipt_number,
            status="success",
        ).one_or_none()
        kind = "payout"
    if row is None:
        return kind, None, None, "unmatched", "No successful tenant payment/refund callback has this receipt"
    expected = Decimal(str(row.amount)).quantize(CENT)
    actual = entry.amount.quantize(CENT)
    if expected != actual:
        return kind, row, expected, "amount_mismatch", f"Statement amount {actual} differs from confirmed amount {expected}"
    return kind, row, expected, "matched", ""


@router.post("", status_code=201)
def import_settlement_statement(payload: SettlementImport,
                                membership=Depends(active_membership),
                                user=Depends(current_user), db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    canonical = _canonical_payload(payload)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    existing = db.query(MpesaSettlementBatch).filter_by(
        organization_id=membership.organization_id,
        idempotency_key=payload.idempotency_key,
    ).first()
    if existing:
        if existing.payload_hash != digest:
            raise HTTPException(409, "Settlement idempotency key was already used with different statement data")
        return _batch_summary(existing)

    batch = MpesaSettlementBatch(
        organization_id=membership.organization_id,
        idempotency_key=payload.idempotency_key,
        payload_hash=digest, source=payload.source, currency=payload.currency,
        imported_by=user.id, total_lines=len(payload.entries),
    )
    db.add(batch)
    db.flush()
    seen = set()
    total = Decimal("0.00")
    matched = Decimal("0.00")
    matched_count = 0
    exceptions = 0
    for entry in payload.entries:
        amount = entry.amount.quantize(CENT)
        total += amount
        if entry.receipt_number in seen:
            kind, row, expected = entry.transaction_type, None, None
            status, detail = "duplicate_in_statement", "Receipt appears more than once in this statement"
        else:
            seen.add(entry.receipt_number)
            kind, row, expected, status, detail = _match_entry(
                db, membership.organization_id, entry
            )
        if status == "matched":
            matched += amount
            matched_count += 1
        else:
            exceptions += 1
        db.add(MpesaSettlementLine(
            organization_id=membership.organization_id, batch_id=batch.id,
            receipt_number=entry.receipt_number, transaction_type=entry.transaction_type,
            transaction_at=entry.transaction_at, amount=amount,
            account_reference=entry.account_reference, matched_type=kind,
            matched_id=row.id if row else None, expected_amount=expected,
            status=status, exception_detail=detail,
        ))
    batch.total_amount = total
    batch.matched_amount = matched
    batch.matched_lines = matched_count
    batch.exception_lines = exceptions
    batch.status = "reconciled" if exceptions == 0 else "review_required"
    db.add(AuditEvent(
        organization_id=membership.organization_id, actor_user_id=user.id,
        action="mpesa.settlement.imported", resource_type="mpesa_settlement_batch",
        resource_id=str(batch.id),
        detail=f"lines:{len(payload.entries)};matched:{matched_count};exceptions:{exceptions};amount:{total}",
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(MpesaSettlementBatch).filter_by(
            organization_id=membership.organization_id,
            idempotency_key=payload.idempotency_key,
        ).first()
        if existing and existing.payload_hash == digest:
            return _batch_summary(existing)
        raise HTTPException(409, "A concurrent settlement import used this idempotency key")
    db.refresh(batch)
    return _batch_summary(batch)


def _batch_summary(batch):
    return {
        "id": batch.id, "status": batch.status, "source": batch.source,
        "currency": batch.currency, "total_lines": batch.total_lines,
        "matched_lines": batch.matched_lines, "exception_lines": batch.exception_lines,
        "total_amount": str(batch.total_amount), "matched_amount": str(batch.matched_amount),
        "imported_at": batch.imported_at.isoformat() if batch.imported_at else None,
    }


@router.get("")
def list_settlement_batches(membership=Depends(active_membership), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    rows = db.query(MpesaSettlementBatch).filter_by(
        organization_id=membership.organization_id
    ).order_by(MpesaSettlementBatch.id.desc()).limit(100).all()
    return [_batch_summary(row) for row in rows]


@router.get("/{batch_id}")
def get_settlement_batch(batch_id: int, membership=Depends(active_membership),
                         db: Session = Depends(get_db)):
    require_permission(membership, "read")
    batch = db.query(MpesaSettlementBatch).filter_by(
        id=batch_id, organization_id=membership.organization_id
    ).first()
    if not batch:
        raise HTTPException(404, "Settlement batch not found")
    lines = db.query(MpesaSettlementLine).filter_by(
        batch_id=batch.id, organization_id=membership.organization_id
    ).order_by(MpesaSettlementLine.id).all()
    return {
        **_batch_summary(batch),
        "lines": [{
            "id": row.id, "receipt_number": row.receipt_number,
            "transaction_type": row.transaction_type,
            "transaction_at": row.transaction_at.isoformat(),
            "amount": str(row.amount), "expected_amount": str(row.expected_amount) if row.expected_amount is not None else None,
            "status": row.status, "exception_detail": row.exception_detail,
            "matched_type": row.matched_type, "matched_id": row.matched_id,
            "account_reference": row.account_reference,
        } for row in lines],
    }
