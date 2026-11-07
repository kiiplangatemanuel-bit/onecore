from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.procurement_workflow_models import (
    ProcurementSettlement, ProcurementSettlementAllocation, ProcurementApprovalDelegation,
    ProcurementSupplierPortalToken, ProcurementInvoiceDiscrepancy,
    ProcurementSupplierStatement, ProcurementSupplierStatementLine,
)
from app.main import app


def test_procurement_workflow_tables_are_registered():
    assert ProcurementSettlement.__tablename__ == "procurement_settlements"
    assert ProcurementSettlementAllocation.__tablename__ == "procurement_settlement_allocations"
    assert ProcurementApprovalDelegation.__tablename__ == "procurement_approval_delegations"
    assert ProcurementSupplierPortalToken.__tablename__ == "procurement_supplier_portal_tokens"
    assert ProcurementInvoiceDiscrepancy.__tablename__ == "procurement_invoice_discrepancies"
    assert ProcurementSupplierStatement.__tablename__ == "procurement_supplier_statements"
    assert ProcurementSupplierStatementLine.__tablename__ == "procurement_supplier_statement_lines"


def test_procurement_workflow_routes_are_registered():
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/v1/procurement/supplier-settlements",
        "/api/v1/procurement/supplier-settlements/{settlement_id}/verify",
        "/api/v1/procurement/supplier-settlements/{settlement_id}/remittance",
        "/api/v1/procurement/supplier-settlements/callbacks/b2c/result/{token}",
        "/api/v1/procurement/supplier-settlements/callbacks/b2c/timeout/{token}",
        "/api/v1/procurement/approval-delegations",
        "/api/v1/procurement/orders/{order_id}/approve-as-delegate",
        "/api/v1/procurement/orders/{order_id}/escalate-approval",
        "/api/v1/procurement/supplier-portal/tokens",
        "/api/v1/procurement/supplier-portal/rfqs",
        "/api/v1/procurement/supplier-portal/rfqs/{rfq_id}/quotes",
        "/api/v1/procurement/supplier-portal/purchase-orders",
        "/api/v1/procurement/supplier-portal/invoices",
        "/api/v1/procurement/supplier-portal/delivery-updates",
        "/api/v1/procurement/supplier-statements",
        "/api/v1/procurement/supplier-statements/{statement_id}/reconcile",
        "/api/v1/procurement/supplier-returns/{return_id}/post-credit-note",
        "/api/v1/procurement/invoice-discrepancies/{discrepancy_id}/resolve",
        "/api/v1/procurement/invoice-discrepancies/{discrepancy_id}/auto-resolve",
        "/api/v1/procurement/accounting-reconciliation",
    }
    assert expected <= paths


def test_settlement_contract_rejects_duplicate_invoice_allocations():
    from app.api.procurement_workflows import SettlementCreateIn
    valid = SettlementCreateIn(
        supplier_id=1, payment_account_id=2, payment_date="2026-11-08",
        provider="manual", reference="PAY-001", idempotency_key="settlement-001",
        allocations=[{"invoice_id": 3, "amount": "100.00"}],
    )
    assert valid.allocations[0].amount == Decimal("100.00")
    with pytest.raises(ValidationError):
        SettlementCreateIn(
            supplier_id=1, payment_account_id=2, payment_date="2026-11-08",
            provider="manual", reference="PAY-001", idempotency_key="settlement-002",
            allocations=[{"invoice_id": 3, "amount": "40.00"},
                         {"invoice_id": 3, "amount": "60.00"}],
        )


def test_supplier_statement_match_requires_exactly_one_target():
    from app.api.procurement_workflows import StatementMatchIn
    assert StatementMatchIn(invoice_id=1).invoice_id == 1
    assert StatementMatchIn(payment_id=1).payment_id == 1
    with pytest.raises(ValidationError):
        StatementMatchIn(invoice_id=1, payment_id=2)
    with pytest.raises(ValidationError):
        StatementMatchIn()


def test_supplier_portal_quote_requires_unique_complete_line_ids():
    from app.api.procurement_workflows import SupplierPortalQuoteIn
    quote = SupplierPortalQuoteIn(
        currency="KES", delivery_days=3,
        lines=[{"rfq_line_id": 1, "unit_price": "10.00"},
               {"rfq_line_id": 2, "unit_price": "20.00"}],
    )
    assert len(quote.lines) == 2
    with pytest.raises(ValidationError):
        SupplierPortalQuoteIn(
            currency="KES", delivery_days=3,
            lines=[{"rfq_line_id": 1, "unit_price": "10.00"},
                   {"rfq_line_id": 1, "unit_price": "11.00"}],
        )


def test_procurement_workflow_migration_is_reversible_and_chained():
    from pathlib import Path
    migration = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0033_procurement_workflows.py"
    source = migration.read_text(encoding="utf-8")
    assert 'revision = "0033_procurement_workflows"' in source
    assert 'down_revision = "0032_crm_forecast_attribution"' in source
    assert 'def upgrade():' in source and 'def downgrade():' in source
    for table in (
        "procurement_settlements", "procurement_settlement_allocations",
        "procurement_approval_delegations", "procurement_supplier_portal_tokens",
        "procurement_invoice_discrepancies", "procurement_supplier_statements",
        "procurement_supplier_statement_lines",
    ):
        assert f'"{table}"' in source
