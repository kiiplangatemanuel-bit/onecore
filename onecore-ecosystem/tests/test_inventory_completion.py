from decimal import Decimal
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.core.inventory_models import (
    InventoryWarehouse, InventoryTransfer, InventoryReservation, InventoryBatch,
    InventoryStocktake, InventoryReorderRule, InventoryPriceList, InventoryPrice,
)
from app.api.inventory_completion import (
    TransferIn, ReservationIn, BatchReceiptIn, BatchIssueIn, StocktakeIn, ReorderRuleIn, PriceIn,
)
from app.main import app


def test_inventory_completion_models_are_registered():
    expected = {
        "inventory_warehouses", "inventory_transfers", "inventory_transfer_lines",
        "inventory_reservations", "inventory_batches", "inventory_stocktakes",
        "inventory_stocktake_lines", "inventory_reorder_rules", "inventory_price_lists",
        "inventory_prices",
    }
    from app.core.database import Base
    assert expected <= set(Base.metadata.tables)
    assert InventoryWarehouse.__tablename__ == "inventory_warehouses"
    assert InventoryTransfer.__tablename__ == "inventory_transfers"
    assert InventoryReservation.__tablename__ == "inventory_reservations"
    assert InventoryBatch.__tablename__ == "inventory_batches"
    assert InventoryStocktake.__tablename__ == "inventory_stocktakes"
    assert InventoryReorderRule.__tablename__ == "inventory_reorder_rules"
    assert InventoryPriceList.__tablename__ == "inventory_price_lists"
    assert InventoryPrice.__tablename__ == "inventory_prices"


def test_inventory_completion_routes_are_registered():
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/v1/inventory/warehouses", "/api/v1/inventory/transfers",
        "/api/v1/inventory/transfers/{transfer_id}/dispatch",
        "/api/v1/inventory/transfers/{transfer_id}/receive",
        "/api/v1/inventory/reservations", "/api/v1/inventory/reservations/{reservation_id}/release",
        "/api/v1/inventory/reservations/expire", "/api/v1/inventory/batches/receive",
        "/api/v1/inventory/batches/issue", "/api/v1/inventory/stocktakes",
        "/api/v1/inventory/stocktakes/{stocktake_id}/approve", "/api/v1/inventory/replenishment",
        "/api/v1/inventory/forecast", "/api/v1/inventory/valuation",
        "/api/v1/inventory/price-lists", "/api/v1/inventory/dashboard", "/api/v1/inventory/alerts",
    }
    assert expected <= paths


def test_transfer_contract_rejects_empty_and_duplicate_product_lines():
    with pytest.raises(ValidationError):
        TransferIn(source_warehouse_id=1, destination_warehouse_id=2, lines=[])
    payload = TransferIn(source_warehouse_id=1, destination_warehouse_id=2,
        lines=[{"product_id": 10, "quantity": "2.500"}])
    assert payload.lines[0].quantity == Decimal("2.500")


def test_reservation_requires_timezone_aware_expiry_and_idempotency_key():
    valid = ReservationIn(warehouse_id=1, product_id=1, source_type="pos_order",
        source_reference="POS-1", quantity="1", expires_at=datetime.now(timezone.utc)+timedelta(hours=1),
        idempotency_key="reserve-0001")
    assert valid.source_type == "pos_order"
    with pytest.raises(ValidationError):
        ReservationIn(warehouse_id=1, product_id=1, source_type="other",
            source_reference="POS-1", quantity="1", expires_at=datetime.now(timezone.utc)+timedelta(hours=1),
            idempotency_key="reserve-0001")


def test_batch_serials_are_single_unit_and_cost_nonnegative():
    valid = BatchReceiptIn(warehouse_id=1, product_id=1, serial_number="SN-001",
        quantity="1", unit_cost="10", idempotency_key="batch-0001")
    assert valid.quantity == Decimal("1")
    with pytest.raises(ValidationError):
        BatchReceiptIn(warehouse_id=1, product_id=1, serial_number="SN-002",
            quantity="2", unit_cost="10", idempotency_key="batch-0002")
    with pytest.raises(ValidationError):
        BatchIssueIn(warehouse_id=1, product_id=1, quantity="1", method="LIFO",
            idempotency_key="issue-0001")


def test_stocktake_reorder_and_retail_price_contracts():
    take = StocktakeIn(warehouse_id=1, lines=[{"product_id": 1, "counted_quantity": "3"}])
    assert take.lines[0].counted_quantity == Decimal("3")
    with pytest.raises(ValidationError):
        ReorderRuleIn(warehouse_id=1, product_id=1, minimum_quantity="10", maximum_quantity="5")
    price = PriceIn(product_id=1, unit_price="15.50", promotion_percent="10")
    assert price.unit_price == Decimal("15.50")
    with pytest.raises(ValidationError):
        PriceIn(product_id=1, unit_price="-1", promotion_percent="101")
