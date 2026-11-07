"""POS checkout validation and offline replay helpers."""
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_pos_line(unit_price: Decimal, quantity: Decimal,
                       discount_percent: Decimal, tax_rate: Decimal):
    """Return gross subtotal, discount, tax and final line amount."""
    subtotal = money(Decimal(unit_price) * Decimal(quantity))
    discount = money(subtotal * Decimal(discount_percent) / Decimal("100"))
    taxable = subtotal - discount
    tax = money(taxable * Decimal(tax_rate) / Decimal("100"))
    return subtotal, discount, tax, money(taxable + tax)


def allocate_return_amounts(original, quantity: Decimal, prior_returned_amount: Decimal):
    """Allocate discounts and tax proportionally; final return absorbs rounding residue."""
    original_qty = Decimal(str(original.quantity))
    remaining_qty = original_qty - Decimal(str(prior_returned_amount[0]))
    remaining_total = Decimal(str(original.line_total)) - Decimal(str(prior_returned_amount[1]))
    if quantity == remaining_qty:
        return remaining_total
    return money(Decimal(str(original.line_total)) * Decimal(quantity) / original_qty)


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
            {"product_id": line.product_id, "quantity": str(line.quantity),
             "discount_percent": str(line.discount_percent)}
            for line in payload.lines
        ], key=lambda x: (x["product_id"], x["quantity"])),
        "payments": sorted([
            {"method": p.method, "amount": str(money(p.amount)),
             "provider_reference": p.provider_reference}
            for p in payload.payments
        ], key=lambda x: (x["method"], x["amount"], x["provider_reference"])),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()



def canonical_return_hash(payload) -> str:
    body = {
        "reason": payload.reason.strip(),
        "lines": sorted(
            [{"sale_line_id": line.sale_line_id, "quantity": str(line.quantity)}
             for line in payload.lines],
            key=lambda item: item["sale_line_id"],
        ),
        "refunds": sorted(
            [{"method": item.method, "amount": str(money(item.amount)),
              "provider_reference": item.provider_reference}
             for item in payload.refunds],
            key=lambda item: (item["method"], item["amount"], item["provider_reference"]),
        ),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_return_refund_total(total: Decimal, refunds) -> None:
    refunded = sum((money(Decimal(str(item.amount))) for item in refunds), Decimal("0.00"))
    if money(total) != refunded:
        raise HTTPException(422, "Refund allocations must equal the return value")
