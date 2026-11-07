from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.models import CRMQuote, CRMQuoteLine, CRMSalesOrder, CRMSalesOrderLine
from app.core.schemas import CRMQuoteIn, CRMQuoteConvertIn
from app.main import app


def test_crm_quote_schema_calculates_valid_contract_fields():
    payload = CRMQuoteIn(
        contact_id=1, quote_number="QT-2026-001", issue_date="2026-11-08",
        valid_until="2026-11-30",
        lines=[{"description":"Implementation service","quantity":"2",
                "unit_price":"1000.00","tax_rate":"16"}])
    assert payload.lines[0].quantity == Decimal("2")
    with pytest.raises(ValidationError):
        CRMQuoteIn(contact_id=1, quote_number="QT-002", issue_date="2026-11-08",
                   valid_until="2026-11-30", lines=[])


def test_crm_quote_models_and_routes_are_registered():
    assert CRMQuote.__tablename__ == "crm_quotes"
    assert CRMQuoteLine.__tablename__ == "crm_quote_lines"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/crm/quotes" in paths
    assert "/api/v1/crm/quotes/{quote_id}" in paths
    assert "/api/v1/crm/quotes/{quote_id}/issue" in paths
    assert "/api/v1/crm/quotes/{quote_id}/accept" in paths
    assert "/api/v1/crm/quotes/{quote_id}/reject" in paths
    assert "/api/v1/crm/forecast" in paths



def test_crm_quote_conversion_contract_and_routes():
    payload = CRMQuoteConvertIn(order_number="SO-QT-2026-001")
    assert payload.order_number == "SO-QT-2026-001"
    assert CRMSalesOrder.__tablename__ == "crm_sales_orders"
    assert CRMSalesOrderLine.__tablename__ == "crm_sales_order_lines"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/crm/quotes/{quote_id}/convert-to-order" in paths
    assert "/api/v1/crm/orders" in paths
    assert "/api/v1/crm/orders/{order_id}" in paths
    with pytest.raises(ValidationError):
        CRMQuoteConvertIn(order_number="invalid order number with spaces")
