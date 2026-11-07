from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.inventory import resulting_balance, validate_stock_delta


def test_receipt_requires_positive_quantity():
    validate_stock_delta("receipt", Decimal("5"))
    with pytest.raises(HTTPException) as exc:
        validate_stock_delta("receipt", Decimal("-1"))
    assert exc.value.status_code == 422


def test_issue_requires_negative_quantity():
    validate_stock_delta("issue", Decimal("-2"))
    with pytest.raises(HTTPException) as exc:
        validate_stock_delta("issue", Decimal("2"))
    assert exc.value.status_code == 422


def test_adjustment_cannot_be_zero():
    validate_stock_delta("adjustment", Decimal("-1"))
    with pytest.raises(HTTPException) as exc:
        validate_stock_delta("adjustment", Decimal("0"))
    assert exc.value.status_code == 422


def test_stock_balance_uses_decimal_precision():
    assert resulting_balance(Decimal("1.250"), Decimal("-0.125")) == Decimal("1.125")


def test_stock_cannot_become_negative():
    with pytest.raises(HTTPException) as exc:
        resulting_balance(Decimal("1"), Decimal("-1.001"))
    assert exc.value.status_code == 409
