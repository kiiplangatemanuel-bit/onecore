from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.models import POSShift, POSCashMovement, POSSale, POSSaleLine, POSPayment
from app.core.schemas import POSSaleSyncIn, POSShiftOpenIn, POSShiftCloseIn, POSCashMovementIn, POSShiftReviewIn
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
    assert "/pos" in paths


def test_pos_return_contracts_idempotency_and_routes():
    from app.core.models import POSReturn, POSReturnLine, POSRefund
    from app.core.schemas import POSReturnIn
    from app.services.pos import canonical_return_hash, validate_return_refund_total

    payload = POSReturnIn(
        client_return_id="return-device-0001",
        reason="Customer returned damaged goods",
        lines=[{"sale_line_id": 12, "quantity": "1.000"}],
        refunds=[{"method": "cash", "amount": "25.00"}],
    )
    assert payload.lines[0].quantity == Decimal("1.000")
    assert canonical_return_hash(payload) == canonical_return_hash(payload)
    validate_return_refund_total(Decimal("25.00"), payload.refunds)
    with pytest.raises(HTTPException) as exc:
        validate_return_refund_total(Decimal("26.00"), payload.refunds)
    assert exc.value.status_code == 422
    with pytest.raises(ValidationError):
        POSReturnIn(
            client_return_id="return-device-0002", reason="Duplicate line test",
            lines=[{"sale_line_id": 12, "quantity": "1"},
                   {"sale_line_id": 12, "quantity": "2"}],
            refunds=[{"method": "cash", "amount": "75.00"}],
        )
    with pytest.raises(ValidationError):
        POSReturnIn(
            client_return_id="return-device-0003", reason="Invalid refund method",
            lines=[{"sale_line_id": 12, "quantity": "1"}],
            refunds=[{"method": "mobilemoney", "amount": "75.00"}],
        )
    assert POSReturn.__tablename__ == "pos_returns"
    assert POSReturnLine.__tablename__ == "pos_return_lines"
    assert POSRefund.__tablename__ == "pos_refunds"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/pos/sales/{sale_id}" in paths
    assert "/api/v1/pos/sales/{sale_id}/returns" in paths


def test_pos_cash_reconciliation_contracts_and_routes():
    payload=POSShiftCloseIn(closing_cash=Decimal("1265.00"),cash_count={"1000":1,"200":1,"50":1,"10":1,"5":1})
    assert payload.closing_cash==Decimal("1265.00")
    with pytest.raises(ValidationError):
        POSShiftCloseIn(closing_cash=Decimal("1264.00"),cash_count={"1000":1,"200":1,"50":1,"10":1,"5":1})
    with pytest.raises(ValidationError):
        POSShiftCloseIn(closing_cash=Decimal("0.00"),cash_count={})
    with pytest.raises(ValidationError):
        POSShiftCloseIn(closing_cash=Decimal("10.00"),cash_count={"2":5})
    assert POSCashMovementIn(movement_type="safe_drop",amount="500.00",reason="Move cash to safe",idempotency_key="safe-drop-001")
    with pytest.raises(ValidationError):
        POSCashMovementIn(movement_type="withdraw",amount="10",reason="Wrong movement",idempotency_key="safe-drop-002")
    with pytest.raises(ValidationError):
        POSShiftReviewIn(decision="approve",note=" ")
    assert POSCashMovement.__tablename__=="pos_cash_movements"
    paths=set(app.openapi()["paths"])
    assert "/api/v1/pos/shifts/{shift_id}/cash-movements" in paths
    assert "/api/v1/pos/shifts/{shift_id}/reconciliation" in paths
    assert "/api/v1/pos/shifts/{shift_id}/review" in paths


def test_offline_sale_hash_includes_customer_membership():
    base = sample_payload()
    linked = POSSaleSyncIn(
        client_transaction_id=base.client_transaction_id, shift_id=base.shift_id,
        branch_id=base.branch_id, customer_id=77, lines=base.lines, payments=base.payments,
    )
    assert canonical_request_hash(base) != canonical_request_hash(linked)



def test_loyalty_redemption_changes_offline_hash_but_zero_preserves_legacy_hash():
    base = sample_payload()
    zero = POSSaleSyncIn(
        client_transaction_id=base.client_transaction_id, shift_id=base.shift_id,
        branch_id=base.branch_id, currency=base.currency, lines=base.lines,
        payments=base.payments, loyalty_points_redeemed=0,
    )
    redeemed = POSSaleSyncIn(
        client_transaction_id=base.client_transaction_id, shift_id=base.shift_id,
        branch_id=base.branch_id, currency=base.currency, lines=base.lines,
        payments=base.payments, loyalty_points_redeemed=100,
    )
    assert canonical_request_hash(base) == canonical_request_hash(zero)
    assert canonical_request_hash(base) != canonical_request_hash(redeemed)
    with pytest.raises(ValidationError):
        POSSaleSyncIn(
            client_transaction_id=base.client_transaction_id, shift_id=base.shift_id,
            branch_id=base.branch_id, lines=base.lines, payments=base.payments,
            loyalty_points_redeemed=-1,
        )


def test_loyalty_redemption_allocates_discount_and_recalculates_mixed_tax_lines():
    from app.services.pos import apply_loyalty_redemption

    prepared = [
        (None, Decimal("100.00"), Decimal("100.00"), Decimal("0.00"),
         Decimal("16.00"), Decimal("16.00"), Decimal("116.00"), Decimal("0.00")),
        (None, Decimal("100.00"), Decimal("100.00"), Decimal("0.00"),
         Decimal("0.00"), Decimal("0.00"), Decimal("100.00"), Decimal("0.00")),
    ]
    lines, discount, tax, total = apply_loyalty_redemption(
        prepared, 100, 100, Decimal("50.00")
    )
    assert discount == Decimal("1.00")
    assert sum((line[7] for line in lines), Decimal("0.00")) == Decimal("1.00")
    assert tax == Decimal("15.92")
    assert total == Decimal("214.92")
    assert all(line[6] > 0 for line in lines)


def test_loyalty_redemption_rejects_points_above_sale_cap_and_subcent_values():
    from app.services.pos import apply_loyalty_redemption

    prepared = [(None, Decimal("10.00"), Decimal("10.00"), Decimal("0.00"),
                 Decimal("0.00"), Decimal("0.00"), Decimal("10.00"), Decimal("0.00"))]
    with pytest.raises(HTTPException) as cap:
        apply_loyalty_redemption(prepared, 100, 100, Decimal("10.00"))
    assert cap.value.status_code == 422
    with pytest.raises(HTTPException) as subcent:
        apply_loyalty_redemption(prepared, 1, 1000, Decimal("50.00"))
    assert subcent.value.status_code == 422



def test_loyalty_points_restore_and_earned_points_reverse_proportionally_on_returns():
    from app.services.pos import calculate_loyalty_return_adjustments

    restore, reverse = calculate_loyalty_return_adjustments(
        points_redeemed=100, points_earned=2,
        cumulative_refunds=Decimal("100.00"), sale_total=Decimal("200.00"),
    )
    assert (restore, reverse) == (50, 1)

    retry_restore, retry_reverse = calculate_loyalty_return_adjustments(
        points_redeemed=100, points_earned=2,
        cumulative_refunds=Decimal("100.00"), sale_total=Decimal("200.00"),
        already_restored=50, already_reversed=1,
    )
    assert (retry_restore, retry_reverse) == (0, 0)

    full_restore, full_reverse = calculate_loyalty_return_adjustments(
        points_redeemed=100, points_earned=2,
        cumulative_refunds=Decimal("200.00"), sale_total=Decimal("200.00"),
        already_restored=50, already_reversed=1,
    )
    assert (full_restore, full_reverse) == (50, 1)
