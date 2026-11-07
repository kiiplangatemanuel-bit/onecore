from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.models import ProcurementSupplier, ProcurementPurchaseOrder, ProcurementPurchaseOrderLine
from app.core.schemas import ProcurementSupplierIn, PurchaseOrderIn, PurchaseOrderReceiptIn
from app.main import app


def test_supplier_contract_requires_name():
    assert ProcurementSupplierIn(name="Acme Supplies").name == "Acme Supplies"
    with pytest.raises(ValidationError):
        ProcurementSupplierIn(name="A")


def test_purchase_order_requires_at_least_one_positive_line():
    order = PurchaseOrderIn(
        supplier_id=1,
        lines=[{"product_id": 1, "quantity": "2.500", "unit_cost": "100.00"}],
    )
    assert order.lines[0].quantity == Decimal("2.500")
    with pytest.raises(ValidationError):
        PurchaseOrderIn(supplier_id=1, lines=[])


def test_goods_receipt_requires_idempotency_key():
    receipt = PurchaseOrderReceiptIn(
        lines=[{"line_id": 1, "quantity": "1.000", "idempotency_key": "grn-line-0001"}]
    )
    assert receipt.lines[0].quantity == Decimal("1.000")
    with pytest.raises(ValidationError):
        PurchaseOrderReceiptIn(
            lines=[{"line_id": 1, "quantity": "1.000", "idempotency_key": "short"}]
        )


def test_procurement_models_and_routes_are_registered():
    assert ProcurementSupplier.__tablename__ == "procurement_suppliers"
    assert ProcurementPurchaseOrder.__tablename__ == "procurement_purchase_orders"
    assert ProcurementPurchaseOrderLine.__tablename__ == "procurement_purchase_order_lines"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/procurement/suppliers" in paths
    assert "/api/v1/procurement/orders" in paths
    assert "/api/v1/procurement/orders/{order_id}/approve" in paths
    assert "/api/v1/procurement/orders/{order_id}/receive" in paths
