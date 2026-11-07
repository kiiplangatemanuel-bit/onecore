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
        "/api/v1/procurement/supplier-statements/{statement_id}/lines/{line_id}/match",
        "/api/v1/procurement/supplier-statements/{statement_id}/reconcile",
        "/api/v1/procurement/supplier-invoices/{supplier_invoice_id}/integrate-to-ap",
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
    assert StatementMatchIn(settlement_id=1).settlement_id == 1
    with pytest.raises(ValidationError):
        StatementMatchIn(invoice_id=1, payment_id=2)
    with pytest.raises(ValidationError):
        StatementMatchIn(invoice_id=1, settlement_id=2)
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


def _procurement_callback_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.core.database import Base
    from app.core.models import MpesaPaymentIntent, MpesaRefundIntent
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[
        ProcurementSettlement.__table__, MpesaPaymentIntent.__table__, MpesaRefundIntent.__table__,
    ])
    return sessionmaker(bind=engine)()


def test_supplier_b2c_callback_confirms_exact_amount_and_receipt_before_posting():
    import hashlib
    from app.api.procurement_workflows import _supplier_b2c_callback
    db = _procurement_callback_session()
    token = "supplier-b2c-test-token"
    row = ProcurementSettlement(
        id=1, organization_id=1, supplier_id=10, payment_account_id=20,
        amount=Decimal("125.00"), currency="KES", provider="mpesa",
        provider_phone_number="254712345678",
        callback_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        status="pending_provider", payment_date=__import__("datetime").datetime(2026, 11, 8),
        idempotency_key="supplier-payment-0001", created_by=1,
    )
    db.add(row)
    db.commit()
    body = {"Result": {
        "ConversationID": "AG_SUPPLIER_1", "OriginatorConversationID": "OR_SUPPLIER_1",
        "ResultCode": 0, "ResultDesc": "Success",
        "ResultParameters": {"ResultParameter": [
            {"Key": "TransactionReceipt", "Value": "QABSUPPLIER001"},
            {"Key": "TransactionAmount", "Value": 125},
        ]},
    }}
    assert _supplier_b2c_callback(db, token, body) is True
    db.refresh(row)
    assert row.status == "provider_confirmed"
    assert row.provider_reference == "QABSUPPLIER001"
    # Provider confirmation is not yet AP settlement: a manager must post it.
    assert row.journal_id is None
    assert _supplier_b2c_callback(db, token, body) is True
    assert row.status == "provider_confirmed"
    db.close()


def test_supplier_b2c_callback_rejects_amount_mismatch_and_duplicate_receipt():
    import hashlib
    from app.api.procurement_workflows import _supplier_b2c_callback
    db = _procurement_callback_session()
    token = "supplier-b2c-duplicate-token"
    duplicate = ProcurementSettlement(
        id=1, organization_id=1, supplier_id=10, payment_account_id=20,
        amount=Decimal("100.00"), currency="KES", provider="mpesa",
        provider_reference="QABUSED", status="failed",
        payment_date=__import__("datetime").datetime(2026, 11, 8),
        idempotency_key="supplier-payment-duplicate", created_by=1,
    )
    row = ProcurementSettlement(
        id=2, organization_id=1, supplier_id=10, payment_account_id=20,
        amount=Decimal("125.00"), currency="KES", provider="mpesa",
        provider_phone_number="254712345678",
        callback_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        status="pending_provider", payment_date=__import__("datetime").datetime(2026, 11, 8),
        idempotency_key="supplier-payment-0002", created_by=1,
    )
    db.add_all([duplicate, row])
    db.commit()
    mismatch = {"Result": {
        "ConversationID": "AG_SUPPLIER_2", "ResultCode": 0,
        "ResultParameters": {"ResultParameter": [
            {"Key": "TransactionReceipt", "Value": "QABUSED"},
            {"Key": "TransactionAmount", "Value": 125},
        ]},
    }}
    assert _supplier_b2c_callback(db, token, mismatch) is True
    db.refresh(row)
    assert row.status == "exception"
    assert row.provider_reference == ""
    db.close()


def test_supplier_b2c_timeout_is_unknown_and_not_marked_settled():
    import hashlib
    from app.api.procurement_workflows import _supplier_b2c_callback
    db = _procurement_callback_session()
    token = "supplier-b2c-timeout-token"
    row = ProcurementSettlement(
        id=3, organization_id=1, supplier_id=10, payment_account_id=20,
        amount=Decimal("75.00"), currency="KES", provider="mpesa",
        callback_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        status="pending_provider", payment_date=__import__("datetime").datetime(2026, 11, 8),
        idempotency_key="supplier-payment-0003", created_by=1,
    )
    db.add(row)
    db.commit()
    body = {"Result": {"ConversationID": "AG_TIMEOUT", "OriginatorConversationID": "OR_TIMEOUT"}}
    assert _supplier_b2c_callback(db, token, body, timeout=True) is True
    db.refresh(row)
    assert row.status == "unknown"
    assert row.journal_id is None
    db.close()


def test_supplier_b2c_callback_rejects_wrong_transaction_amount():
    import hashlib
    from datetime import datetime
    from app.api.procurement_workflows import _supplier_b2c_callback
    db = _procurement_callback_session()
    token = "supplier-b2c-wrong-amount"
    row = ProcurementSettlement(
        id=4, organization_id=1, supplier_id=10, payment_account_id=20,
        amount=Decimal("125.00"), currency="KES", provider="mpesa",
        callback_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        status="pending_provider", payment_date=datetime(2026, 11, 8),
        idempotency_key="supplier-payment-0004", created_by=1,
    )
    db.add(row)
    db.commit()
    body = {"Result": {
        "ConversationID": "AG_WRONG_AMOUNT", "ResultCode": 0,
        "ResultParameters": {"ResultParameter": [
            {"Key": "TransactionReceipt", "Value": "QABWRONG"},
            {"Key": "TransactionAmount", "Value": 124},
        ]},
    }}
    assert _supplier_b2c_callback(db, token, body) is True
    db.refresh(row)
    assert row.status == "exception"
    assert row.provider_reference == ""
    assert row.journal_id is None
    db.close()
