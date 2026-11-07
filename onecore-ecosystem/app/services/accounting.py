"""Double-entry accounting invariants."""
from decimal import Decimal
from fastapi import HTTPException


def validate_journal_lines(lines):
    if len(lines) < 2:
        raise HTTPException(422, "A journal requires at least two lines")
    debit = sum((Decimal(str(line.debit)) for line in lines), Decimal("0"))
    credit = sum((Decimal(str(line.credit)) for line in lines), Decimal("0"))
    if debit <= 0 or credit <= 0 or debit != credit:
        raise HTTPException(422, "Journal debits and credits must be equal and greater than zero")
    for line in lines:
        d, c = Decimal(str(line.debit)), Decimal(str(line.credit))
        if d < 0 or c < 0 or (d > 0 and c > 0) or (d == 0 and c == 0):
            raise HTTPException(422, "Each journal line must contain either a debit or a credit")
    return debit, credit
