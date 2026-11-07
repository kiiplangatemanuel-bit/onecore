from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.models import AccountingInvoice, AccountingInvoiceLine, AccountingInvoicePayment
from app.core.schemas import AccountingInvoiceIn, AccountingInvoicePaymentIn
from app.main import app


def test_ar_ap_invoice_contracts_require_valid_type_and_lines():
    payload = AccountingInvoiceIn(
        invoice_type="receivable", contact_id=1, invoice_number="INV-001",
        issue_date="2026-11-08", due_date="2026-11-30", control_account_id=10,
        lines=[{"account_id": 20, "description": "Consulting", "quantity": "2",
                "unit_price": "500.00", "tax_rate": "16"}])
    assert payload.invoice_type == "receivable"
    assert payload.lines[0].quantity == Decimal("2")
    with pytest.raises(ValidationError):
        AccountingInvoiceIn(
            invoice_type="invalid", contact_id=1, invoice_number="INV-002",
            issue_date="2026-11-08", due_date="2026-11-30", control_account_id=10,
            lines=[{"account_id": 20, "description": "Service", "quantity": 1, "unit_price": 10}])
    with pytest.raises(ValidationError):
        AccountingInvoiceIn(
            invoice_type="payable", supplier_id=1, invoice_number="INV-003",
            issue_date="2026-11-08", due_date="2026-11-30", control_account_id=10,
            lines=[])


def test_invoice_payment_requires_positive_amount_and_idempotency_key():
    p = AccountingInvoicePaymentIn(payment_account_id=1, amount="100.00",
                                   payment_date="2026-11-08", idempotency_key="receipt-0001")
    assert p.amount == Decimal("100.00")
    with pytest.raises(ValidationError):
        AccountingInvoicePaymentIn(payment_account_id=1, amount=0,
                                   payment_date="2026-11-08", idempotency_key="receipt-0001")


def test_ar_ap_models_and_routes_are_registered():
    assert AccountingInvoice.__tablename__ == "accounting_invoices"
    assert AccountingInvoiceLine.__tablename__ == "accounting_invoice_lines"
    assert AccountingInvoicePayment.__tablename__ == "accounting_invoice_payments"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/accounting/invoices" in paths
    assert "/api/v1/accounting/invoices/{invoice_id}/post" in paths
    assert "/api/v1/accounting/invoices/{invoice_id}/payments" in paths
    assert "/api/v1/accounting/aging" in paths
