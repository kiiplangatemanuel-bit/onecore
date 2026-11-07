from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.models import ProcurementSupplier, ProcurementPurchaseOrder, ProcurementPurchaseOrderLine, ProcurementRequisition, ProcurementRequisitionLine
from app.core.schemas import ProcurementSupplierIn, PurchaseOrderIn, PurchaseOrderReceiptIn, ProcurementRequisitionIn, ProcurementRequisitionReviewIn
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
    assert "/api/v1/procurement/orders/{order_id}" in paths
    assert "/procurement" in paths


def test_requisition_payload_requires_unique_products_and_positive_quantities():
    valid = ProcurementRequisitionIn(
        justification="Replacement stock required for branch operations",
        lines=[{"product_id": 1, "quantity": "2.500"}, {"product_id": 2, "quantity": "1"}],
    )
    assert valid.lines[0].quantity == Decimal("2.500")
    with pytest.raises(ValidationError):
        ProcurementRequisitionIn(
            justification="Replacement stock required",
            lines=[{"product_id": 1, "quantity": "1"}, {"product_id": 1, "quantity": "2"}],
        )
    with pytest.raises(ValidationError):
        ProcurementRequisitionIn(
            justification="Need more stock",
            lines=[{"product_id": 1, "quantity": "0"}],
        )
    with pytest.raises(ValidationError):
        ProcurementRequisitionIn(justification="bad", lines=[{"product_id": 1, "quantity": "1"}])


def test_requisition_review_reason_is_bounded():
    assert ProcurementRequisitionReviewIn(reason="Budget not approved").reason.startswith("Budget")
    with pytest.raises(ValidationError):
        ProcurementRequisitionReviewIn(reason="x" * 501)


def test_requisition_models_and_workflow_routes_are_registered():
    assert ProcurementRequisition.__tablename__ == "procurement_requisitions"
    assert ProcurementRequisitionLine.__tablename__ == "procurement_requisition_lines"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/procurement/requisitions" in paths
    assert "/api/v1/procurement/requisitions/{requisition_id}" in paths
    assert "/api/v1/procurement/requisitions/{requisition_id}/submit" in paths
    assert "/api/v1/procurement/requisitions/{requisition_id}/approve" in paths
    assert "/api/v1/procurement/requisitions/{requisition_id}/reject" in paths


def test_procurement_workspace_exposes_requisition_controls():
    from pathlib import Path
    page = Path(__file__).resolve().parents[1] / "app" / "web" / "procurement.html"
    html = page.read_text(encoding="utf-8")
    assert 'id="requisition"' in html
    assert 'id="requisitions"' in html
    assert "/procurement/requisitions" in html
    assert "/submit" in html
    assert "/approve" in html
    assert "/reject" in html


def test_goods_receipt_inspection_payload_requires_full_accounting_and_reasons():
    from app.core.schemas import GoodsReceiptIn, GoodsReceiptInspectionIn
    valid_receipt = GoodsReceiptIn(lines=[
        {"line_id": 1, "quantity": "5", "idempotency_key": "grn-receipt-0001"}
    ])
    assert valid_receipt.lines[0].quantity == Decimal("5")
    with pytest.raises(ValidationError):
        GoodsReceiptIn(lines=[
            {"line_id": 1, "quantity": "1", "idempotency_key": "duplicate-0001"},
            {"line_id": 1, "quantity": "1", "idempotency_key": "duplicate-0002"},
        ])
    valid_inspection = GoodsReceiptInspectionIn(lines=[
        {"receipt_line_id": 1, "quantity_accepted": "4", "quantity_rejected": "1",
         "rejection_reason": "Damaged packaging"}
    ], note="Inspected on delivery")
    assert valid_inspection.lines[0].quantity_accepted == Decimal("4")
    with pytest.raises(ValidationError):
        GoodsReceiptInspectionIn(lines=[
            {"receipt_line_id": 1, "quantity_accepted": "0", "quantity_rejected": "1"}
        ])
    with pytest.raises(ValidationError):
        GoodsReceiptInspectionIn(lines=[
            {"receipt_line_id": 1, "quantity_accepted": "0", "quantity_rejected": "0"}
        ])


def test_grn_models_and_inspection_routes_are_registered():
    from app.core.models import ProcurementGoodsReceipt, ProcurementGoodsReceiptLine
    assert ProcurementGoodsReceipt.__tablename__ == "procurement_goods_receipts"
    assert ProcurementGoodsReceiptLine.__tablename__ == "procurement_goods_receipt_lines"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/procurement/orders/{order_id}/goods-receipts" in paths
    assert "/api/v1/procurement/goods-receipts" in paths
    assert "/api/v1/procurement/goods-receipts/{receipt_id}" in paths
    assert "/api/v1/procurement/goods-receipts/{receipt_id}/inspect" in paths


def test_legacy_direct_goods_receipt_is_deprecated():
    operation = app.openapi()["paths"]["/api/v1/procurement/orders/{order_id}/receive"]["post"]
    assert operation.get("deprecated") is True


def test_procurement_workspace_mentions_goods_receipt_inspection():
    from pathlib import Path
    page = Path(__file__).resolve().parents[1] / "app" / "web" / "procurement.html"
    html = page.read_text(encoding="utf-8")
    assert "goods-receipts" in html
    assert "inspect" in html
