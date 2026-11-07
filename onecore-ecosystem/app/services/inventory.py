"""Inventory domain rules kept independent of HTTP handlers."""
from decimal import Decimal
from fastapi import HTTPException


def validate_stock_delta(movement_type: str, quantity_delta: Decimal) -> None:
    if movement_type == "receipt" and quantity_delta <= 0:
        raise HTTPException(422, "Receipt quantity must be positive")
    if movement_type == "issue" and quantity_delta >= 0:
        raise HTTPException(422, "Issue quantity must be negative")
    if movement_type == "adjustment" and quantity_delta == 0:
        raise HTTPException(422, "Adjustment quantity cannot be zero")


def resulting_balance(current: Decimal, delta: Decimal) -> Decimal:
    balance = current + delta
    if balance < 0:
        raise HTTPException(409, "Insufficient stock for this issue or adjustment")
    return balance
