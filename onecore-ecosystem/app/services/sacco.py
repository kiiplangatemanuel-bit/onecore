"""SACCO loan schedule arithmetic and repayment allocation helpers."""
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext


CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def build_repayment_schedule(principal, annual_rate, term_months, method, first_due_date):
    principal = money(Decimal(str(principal)))
    annual_rate = Decimal(str(annual_rate))
    if principal <= 0 or term_months < 1 or annual_rate < 0 or method not in {"flat", "reducing"}:
        raise ValueError("Invalid loan schedule inputs")
    with localcontext() as ctx:
        ctx.prec = 28
        monthly_rate = annual_rate / Decimal("1200")
        if method == "flat":
            total_interest = money(principal * annual_rate / Decimal("100") *
                                   Decimal(term_months) / Decimal("12"))
            monthly_interest = money(total_interest / Decimal(term_months))
            remaining_interest = total_interest
            remaining_principal = principal
            rows = []
            for installment in range(1, term_months + 1):
                principal_due = money(remaining_principal if installment == term_months
                                      else principal / Decimal(term_months))
                interest_due = money(remaining_interest if installment == term_months
                                     else monthly_interest)
                remaining_principal = money(remaining_principal - principal_due)
                remaining_interest = money(remaining_interest - interest_due)
                rows.append({"installment_number": installment,
                    "due_date": add_months(first_due_date, installment - 1),
                    "principal_due": principal_due, "interest_due": interest_due})
            return rows
        if monthly_rate == 0:
            payment = principal / Decimal(term_months)
        else:
            payment = principal * monthly_rate / (Decimal("1") - (Decimal("1") + monthly_rate) ** (-term_months))
        payment = money(payment)
        balance = principal
        rows = []
        for installment in range(1, term_months + 1):
            interest_due = money(balance * monthly_rate)
            principal_due = money(balance if installment == term_months
                                  else payment - interest_due)
            if principal_due <= 0:
                raise ValueError("Loan terms produce a non-amortizing schedule")
            if principal_due > balance:
                principal_due = balance
            balance = money(balance - principal_due)
            rows.append({"installment_number": installment,
                "due_date": add_months(first_due_date, installment - 1),
                "principal_due": principal_due, "interest_due": interest_due})
        if balance != 0:
            raise ValueError("Loan schedule did not amortize principal")
        return rows


def allocate_repayment(amount, schedule_rows):
    remaining = money(Decimal(str(amount)))
    principal_paid = Decimal("0.00")
    interest_paid = Decimal("0.00")
    allocations = []
    for row in schedule_rows:
        if remaining <= 0:
            break
        interest_due = money(Decimal(str(row.interest_due)) - Decimal(str(row.interest_paid)))
        principal_due = money(Decimal(str(row.principal_due)) - Decimal(str(row.principal_paid)))
        interest_part = min(remaining, max(interest_due, Decimal("0.00")))
        remaining = money(remaining - interest_part)
        principal_part = min(remaining, max(principal_due, Decimal("0.00")))
        remaining = money(remaining - principal_part)
        if interest_part or principal_part:
            allocations.append((row, interest_part, principal_part))
            interest_paid += interest_part
            principal_paid += principal_part
    if remaining > 0:
        raise ValueError("Repayment exceeds outstanding scheduled principal and interest")
    return money(principal_paid), money(interest_paid), allocations
