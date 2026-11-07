"""HR date calculations shared by leave workflows."""
from datetime import date, timedelta


def business_days(start: date, end: date) -> int:
    """Count weekdays inclusively; public holidays are not subtracted."""
    if end < start:
        raise ValueError("End date cannot precede start date")
    total = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            total += 1
        current += timedelta(days=1)
    return total



def worked_minutes(start, end) -> int:
    """Return completed whole minutes between UTC timestamps."""
    from datetime import timezone
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    elapsed = int((end - start).total_seconds() // 60)
    if elapsed < 0:
        raise ValueError("End timestamp cannot precede start timestamp")
    return elapsed



def payroll_money(value):
    from decimal import Decimal, ROUND_HALF_UP
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def payroll_item_hash(payload) -> str:
    import hashlib
    import json
    body = {
        "employee_id": payload.employee_id,
        "item_type": payload.item_type,
        "code": payload.code.strip().upper(),
        "description": payload.description.strip(),
        "amount": str(payroll_money(payload.amount)),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def payroll_totals(base_pay, items):
    earnings = sum((payroll_money(x.amount) for x in items if x.item_type == "earning"), Decimal("0.00"))
    deductions = sum((payroll_money(x.amount) for x in items if x.item_type == "deduction"), Decimal("0.00"))
    gross = payroll_money(payroll_money(base_pay) + earnings)
    deductions = payroll_money(deductions)
    if deductions > gross:
        raise ValueError("Payroll deductions cannot exceed gross pay")
    return gross, deductions, payroll_money(gross - deductions)
