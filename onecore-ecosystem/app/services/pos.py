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
    if getattr(payload,"customer_id",None) is not None:
        body["customer_id"] = payload.customer_id
    loyalty_points_redeemed = int(getattr(payload, "loyalty_points_redeemed", 0) or 0)
    if loyalty_points_redeemed:
        body["loyalty_points_redeemed"] = loyalty_points_redeemed
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


def apply_loyalty_redemption(prepared, points: int, points_per_currency_unit: int,
                            max_redemption_percent: Decimal):
    """Apply a pre-tax points discount proportionally and recalculate each line's tax.

    Prepared line tuples are (line, unit_price, subtotal, manager_discount,
    tax_rate, tax, line_total, loyalty_discount). The last tuple item is
    replaced with the allocated loyalty discount for a redemption.
    """
    if points <= 0:
        return prepared, Decimal("0.00"), money(sum((item[5] for item in prepared), Decimal("0.00"))), money(sum((item[6] for item in prepared), Decimal("0.00")))
    if points_per_currency_unit <= 0:
        raise HTTPException(409, "Loyalty conversion policy is invalid")
    loyalty_discount = money(Decimal(points) / Decimal(points_per_currency_unit))
    discountable_base = money(sum(
        (Decimal(item[2]) - Decimal(item[3]) for item in prepared), Decimal("0.00")
    ))
    maximum = money(discountable_base * Decimal(max_redemption_percent) / Decimal("100"))
    if loyalty_discount <= 0:
        raise HTTPException(422, "The selected loyalty points are worth less than one cent")
    if loyalty_discount > maximum:
        raise HTTPException(422, "Loyalty redemption exceeds the configured per-sale percentage limit")
    remaining = loyalty_discount
    adjusted = []
    for index, item in enumerate(prepared):
        line, unit_price, subtotal, discount, tax_rate, tax, line_total, _ = item
        taxable_base = money(Decimal(subtotal) - Decimal(discount))
        if index == len(prepared) - 1:
            share = remaining
        else:
            raw = loyalty_discount * taxable_base / discountable_base
            share = (raw * Decimal("100")).to_integral_value(rounding=ROUND_DOWN) / Decimal("100")
            share = min(money(share), remaining, taxable_base)
        remaining = money(remaining - share)
        new_taxable = money(Decimal(subtotal) - Decimal(discount) - share)
        new_tax = money(new_taxable * Decimal(tax_rate) / Decimal("100"))
        new_total = money(new_taxable + new_tax)
        adjusted.append((line, unit_price, subtotal, discount, tax_rate, new_tax, new_total, share))
    return (
        adjusted,
        loyalty_discount,
        money(sum((item[5] for item in adjusted), Decimal("0.00"))),
        money(sum((item[6] for item in adjusted), Decimal("0.00"))),
    )
