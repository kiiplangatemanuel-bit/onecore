"""Pure SACCO loan affordability and reducing-balance schedule calculations."""
import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext

CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def monthly_installment(principal: Decimal, annual_interest_rate_bps: int, term_months: int) -> Decimal:
    principal = _money(Decimal(principal))
    if principal <= 0 or not 1 <= int(term_months) <= 120:
        raise ValueError("Principal and term must be positive and within supported limits")
    if not 0 <= int(annual_interest_rate_bps) <= 6000:
        raise ValueError("Annual interest rate must be between 0 and 60 percent")
    with localcontext() as context:
        context.prec = 32
        monthly_rate = Decimal(annual_interest_rate_bps) / Decimal(120000)
        if monthly_rate == 0:
            return _money(principal / Decimal(term_months))
        payment = principal * monthly_rate / (Decimal(1) - (Decimal(1) + monthly_rate) ** (-int(term_months)))
        return _money(payment)


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def projected_schedule(
    principal: Decimal,
    annual_interest_rate_bps: int,
    term_months: int,
    first_repayment_date: date,
) -> list[dict]:
    principal = _money(Decimal(principal))
    payment = monthly_installment(principal, annual_interest_rate_bps, term_months)
    monthly_rate = Decimal(annual_interest_rate_bps) / Decimal(120000)
    balance = principal
    rows = []
    for number in range(1, term_months + 1):
        interest = _money(balance * monthly_rate)
        principal_due = balance if number == term_months else min(balance, _money(payment - interest))
        total_due = _money(principal_due + interest)
        balance = _money(balance - principal_due)
        rows.append({
            "installment_number": number,
            "due_date": _add_months(first_repayment_date, number - 1),
            "principal_due": principal_due,
            "interest_due": interest,
            "total_due": total_due,
        })
    if balance != Decimal("0.00") or sum((row["principal_due"] for row in rows), Decimal("0.00")) != principal:
        raise ArithmeticError("Projected schedule does not amortize the requested principal")
    return rows


def allocate_due_repayment(amount: Decimal, installments) -> list[dict]:
    """Allocate a partial receipt oldest-due first, applying interest before principal."""
    remaining = _money(amount)
    allocations = []
    for installment in installments:
        if remaining <= 0:
            break
        interest_outstanding = _money(installment.interest_due - installment.interest_paid)
        principal_outstanding = _money(installment.principal_due - installment.principal_paid)
        interest_amount = min(remaining, interest_outstanding)
        remaining = _money(remaining - interest_amount)
        principal_amount = min(remaining, principal_outstanding)
        remaining = _money(remaining - principal_amount)
        if interest_amount or principal_amount:
            allocations.append({
                "installment_id": installment.id,
                "principal_amount": principal_amount,
                "interest_amount": interest_amount,
            })
    if remaining > 0:
        raise ValueError("Repayment exceeds the outstanding amount due on its value date")
    return allocations
