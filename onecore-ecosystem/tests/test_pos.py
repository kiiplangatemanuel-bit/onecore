from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.models import POSShift, POSSale, POSSaleLine, POSPayment
from app.core.schemas import POSSaleSyncIn, POSShiftOpenIn
from app.services.pos import canonical_request_hash, validate_payment_total
from app.main import app


def sample_payload():
    return POSSaleSyncIn(
        client_transaction_id="device-01-sale-0001",
        shift_id=1,
        branch_id="branch-001",
        lines=[{"product_id": 2, "quantity": "2.000"}],
        payments=[{"method": "cash", "amount": "50.00"}],
    )


def test_pos_payment_allocation_must_equal_total():
    validate_payment_total(Decimal("50.00"), sample_payload().payments)
    with pytest.raises(HTTPException) as exc:
        validate_payment_total(Decimal("51.00"), sample_payload().payments)
    assert exc.value.status_code == 422


def test_offline_request_hash_is_stable_and_sensitive_to_transaction_data():
    first = sample_payload()
    second = sample_payload()
    assert canonical_request_hash(first) == canonical_request_hash(second)
    second.lines[0].quantity = Decimal("3.000")
    assert canonical_request_hash(first) != canonical_request_hash(second)


def test_pos_contract_requires_transaction_id_and_positive_quantity():
    assert sample_payload().lines[0].quantity == Decimal("2.000")
    with pytest.raises(ValidationError):
        POSSaleSyncIn(client_transaction_id="x", shift_id=1, branch_id="branch-001",
                      lines=[{"product_id": 2, "quantity": "0"}],
                      payments=[{"method": "cash", "amount": "10"}])


def test_pos_models_and_routes_are_registered():
    assert POSShift.__tablename__ == "pos_shifts"
    assert POSSale.__tablename__ == "pos_sales"
    assert POSSaleLine.__tablename__ == "pos_sale_lines"
    assert POSPayment.__tablename__ == "pos_payments"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/pos/catalog" in paths
    assert "/api/v1/pos/shifts/open" in paths
    assert "/api/v1/pos/shifts/{shift_id}/close" in paths
    assert "/api/v1/pos/sync" in paths
