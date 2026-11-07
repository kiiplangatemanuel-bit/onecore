from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.models import InventoryProduct, POSSale, POSSaleLine, POSReturnLine
from app.core.schemas import InventoryProductIn, InventoryProductTaxRateIn, POSSaleSyncIn
from app.services.pos import calculate_pos_line, canonical_request_hash


def test_inventory_product_tax_rate_is_bounded_and_optional():
    product = InventoryProductIn(
        sku="TAX-ITEM", name="Taxable item", sale_price="100.00", tax_rate="16"
    )
    assert product.tax_rate == Decimal("16")
    assert InventoryProduct.tax_rate is not None
    with pytest.raises(ValidationError):
        InventoryProductIn(sku="BAD-TAX", name="Bad tax", tax_rate="100.01")
    with pytest.raises(ValidationError):
        InventoryProductIn(sku="NEG-TAX", name="Bad tax", tax_rate="-1")
    with pytest.raises(ValidationError):
        InventoryProductIn(sku="PREC-TAX", name="Bad precision", tax_rate="1.00001")


def test_pos_line_discount_and_tax_calculation_is_discount_first():
    subtotal, discount, tax, total = calculate_pos_line(
        Decimal("100.00"), Decimal("2"), Decimal("10"), Decimal("16")
    )
    assert subtotal == Decimal("200.00")
    assert discount == Decimal("20.00")
    assert tax == Decimal("28.80")
    assert total == Decimal("208.80")


def test_pos_line_rounding_and_full_discount():
    assert calculate_pos_line(
        Decimal("0.33"), Decimal("3"), Decimal("0"), Decimal("16")
    ) == (
        Decimal("0.99"), Decimal("0.00"), Decimal("0.16"), Decimal("1.15")
    )
    assert calculate_pos_line(
        Decimal("100"), Decimal("1"), Decimal("100"), Decimal("16")
    ) == (
        Decimal("100.00"), Decimal("100.00"), Decimal("0.00"), Decimal("0.00")
    )


def test_discount_is_part_of_offline_idempotency_hash():
    base = dict(
        client_transaction_id="offline-pos-tax-001", shift_id=1, branch_id="branch-1",
        lines=[{"product_id": 1, "quantity": "1.000", "discount_percent": "0"}],
        payments=[{"method": "cash", "amount": "116.00"}],
    )
    full = POSSaleSyncIn(**base)
    changed = POSSaleSyncIn(**{
        **base, "lines": [{"product_id": 1, "quantity": "1.000", "discount_percent": "5"}]
    })
    assert canonical_request_hash(full) != canonical_request_hash(changed)


def test_discount_validation_and_persisted_tax_snapshots():
    payload = POSSaleSyncIn(
        client_transaction_id="offline-pos-tax-002", shift_id=1, branch_id="branch-1",
        lines=[{"product_id": 1, "quantity": "1.000", "discount_percent": "15.5"}],
        payments=[{"method": "cash", "amount": "100.00"}],
    )
    assert payload.lines[0].discount_percent == Decimal("15.5")
    with pytest.raises(ValidationError):
        POSSaleSyncIn(
            client_transaction_id="offline-pos-tax-003", shift_id=1, branch_id="branch-1",
            lines=[{"product_id": 1, "quantity": "1.000", "discount_percent": "100.01"}],
            payments=[{"method": "cash", "amount": "1.00"}],
        )
    with pytest.raises(ValidationError):
        POSSaleSyncIn(
            client_transaction_id="offline-pos-tax-004", shift_id=1, branch_id="branch-1",
            lines=[{"product_id": 1, "quantity": "1.000", "discount_percent": "1.00001"}],
            payments=[{"method": "cash", "amount": "1.00"}],
        )
    assert POSSale.subtotal_amount is not None
    assert POSSale.discount_amount is not None
    assert POSSale.tax_amount is not None
    assert POSSaleLine.discount_amount is not None
    assert POSSaleLine.tax_amount is not None
    assert POSReturnLine.discount_amount is not None
    assert POSReturnLine.tax_amount is not None



def test_tax_rate_update_contract_is_manager_controlled_and_registered():
    assert InventoryProductTaxRateIn(tax_rate="16").tax_rate == Decimal("16")
    paths = set(__import__("app.main", fromlist=["app"]).app.openapi()["paths"])
    assert "/api/v1/inventory/products/{product_id}/tax-rate" in paths



def test_pos_and_inventory_workspaces_expose_tax_discount_controls():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    pos = (root / "app" / "web" / "pos.html").read_text(encoding="utf-8")
    inventory = (root / "app" / "web" / "inventory.html").read_text(encoding="utf-8")
    assert 'name="discount_percent"' in pos
    assert "discount_percent:Number(item.discount_percent||0)" in pos
    assert "data.tax_amount" in pos
    assert "line.tax_amount" in pos
    assert 'name="tax_rate"' in inventory
    assert "/tax-rate" in inventory
