"""POS checkout validation and offline replay helpers."""
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def validate_payment_total(total: Decimal, payments) -> None:
    paid = sum((money(Decimal(str(p.amount))) for p in payments), Decimal("0.00"))
    if money(total) != paid:
        raise HTTPException(422, "Payment allocations must equal the sale total")


def canonical_request_hash(payload) -> str:
    body = {
        "branch_id": payload.branch_id,
        "shift_id": payload.shift_id,
        "currency": payload.currency,
        "lines": sorted([
            {"product_id": line.product_id, "quantity": str(line.quantity)}
            for line in payload.lines
        ], key=lambda x: (x["product_id"], x["quantity"])),
        "payments": sorted([
            {"method": p.method, "amount": str(money(p.amount)),
             "provider_reference": p.provider_reference}
            for p in payload.payments
        ], key=lambda x: (x["method"], x["amount"], x["provider_reference"])),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
