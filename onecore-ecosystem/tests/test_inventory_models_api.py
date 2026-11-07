from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.models import InventoryProduct, InventoryStockMovement
from app.core.schemas import InventoryMovementIn, InventoryProductIn
from app.main import app


def test_inventory_tables_and_tenant_indexes_exist():
    assert InventoryProduct.__tablename__ == "inventory_products"
    assert InventoryStockMovement.__tablename__ == "inventory_stock_movements"
    product_indexes = {index.name for index in InventoryProduct.__table__.indexes}
    movement_indexes = {index.name for index in InventoryStockMovement.__table__.indexes}
    assert "ix_inventory_product_org_sku" in product_indexes
    assert "ix_inventory_movement_org_idempotency" in movement_indexes


def test_inventory_product_contract_normalizes_at_service_boundary():
    product = InventoryProductIn(sku="abc-123", name="Flour", unit="kg")
    assert product.sku == "abc-123"
    assert product.name == "Flour"


def test_inventory_product_contract_rejects_invalid_sku():
    with pytest.raises(ValidationError):
        InventoryProductIn(sku="bad sku", name="Flour")


def test_stock_movement_contract_requires_idempotency_key():
    movement = InventoryMovementIn(
        product_id=1, quantity_delta=Decimal("2.500"),
        movement_type="receipt", idempotency_key="receipt-0001"
    )
    assert movement.quantity_delta == Decimal("2.500")
    with pytest.raises(ValidationError):
        InventoryMovementIn(product_id=1, quantity_delta=Decimal("1"),
                            movement_type="receipt", idempotency_key="short")


def test_inventory_api_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert "/api/v1/inventory/products" in paths
    assert "/api/v1/inventory/stock" in paths
    assert "/api/v1/inventory/movements" in paths
    assert "/inventory" in paths
