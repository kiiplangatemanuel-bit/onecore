"""SACCO loan arithmetic with explicit flat-interest and repayment allocation rules."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_UP

CENT = Decimal("0.01")
RATIO_QUANTUM = Decimal("0.0001")
MAX_STORED_RATIO = Decimal("999.9999")
MAX_STORED_AMOUNT = Decimal("9999999999999999.99")


def money(value: Decimal | str | int) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_flat_loan_terms(
    principal: Decimal,
    annual_interest_rate: Decimal,
    term_months: int,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return total flat interest, total due and a rounded-up regular instalment.

    The final instalment may be slightly lower to clear the exact total due.
    Rates are annual percentages, not fractions.
    """
    principal = money(principal)
    rate = Decimal(str(annual_interest_rate))
    if principal <= 0 or rate < 0 or rate > 100 or not 1 <= int(term_months) <= 120:
        raise ValueError("Loan terms are outside supported limits")
    interest = money(principal * rate * Decimal(int(term_months)) / Decimal("1200"))
    total_due = money(principal + interest)
    if total_due > MAX_STORED_AMOUNT:
        raise ValueError("Calculated loan amount exceeds supported ledger precision")
    installment = (total_due / Decimal(int(term_months))).quantize(CENT, rounding=ROUND_UP)
    return interest, total_due, installment


def calculate_debt_service_ratio(
    monthly_net_income: Decimal,
    existing_monthly_debt: Decimal,
    proposed_installment: Decimal,
) -> Decimal:
    income = money(monthly_net_income)
    debt = money(existing_monthly_debt)
    installment = money(proposed_installment)
    if income <= 0 or debt < 0 or installment < 0:
        raise ValueError("Income must be positive and monthly debt/instalment cannot be negative")
    ratio = ((debt + installment) / income).quantize(RATIO_QUANTUM, rounding=ROUND_HALF_UP)
    if ratio > MAX_STORED_RATIO:
        raise ValueError("Debt-service ratio exceeds supported precision")
    return ratio


def allocate_repayment(
    amount: Decimal,
    principal_due: Decimal,
    interest_due: Decimal,
) -> tuple[Decimal, Decimal]:
    """Allocate repayment to accrued flat interest first, then principal.

    Returns signed principal and interest deltas for an append-only ledger entry.
    """
    amount = money(amount)
    principal_due = money(principal_due)
    interest_due = money(interest_due)
    if amount <= 0 or principal_due < 0 or interest_due < 0:
        raise ValueError("Repayment and outstanding balances are invalid")
    total_due = money(principal_due + interest_due)
    if amount > total_due:
        raise ValueError("Repayment exceeds the outstanding loan balance")
    interest_paid = min(amount, interest_due)
    principal_paid = money(amount - interest_paid)
    return -principal_paid, -interest_paid
