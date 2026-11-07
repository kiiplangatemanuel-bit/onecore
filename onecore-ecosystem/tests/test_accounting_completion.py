from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.models import AccountingRefund, AccountingProcurementLink
from app.api.accounting_completion import (AccountingRefundIn, ProcurementAPIntegrationIn, AccountingYearEndCloseIn)
from app.main import app


def test_accounting_completion_models_and_payloads():
    assert AccountingRefund.__tablename__ == "accounting_refunds"
    assert AccountingProcurementLink.__tablename__ == "accounting_procurement_links"

    refund = AccountingRefundIn(
        payment_account_id=1, amount="125.00", refund_date="2026-11-07",
        reference="CN-REFUND-01", idempotency_key="refund-key-0001",
    )
    assert refund.amount == Decimal("125.00")
    with pytest.raises(ValidationError):
        AccountingRefundIn(
            payment_account_id=1, amount="0", refund_date="2026-11-07",
            idempotency_key="refund-key-0002",
        )
    with pytest.raises(ValidationError):
        AccountingRefundIn(
            payment_account_id=1, amount="1.005", refund_date="2026-11-07",
            idempotency_key="refund-key-0003",
        )

    mapping = ProcurementAPIntegrationIn(
        due_date="2026-11-30", payable_control_account_id=2,
        tax_account_id=3,
        lines=[{"supplier_invoice_line_id": 10, "expense_account_id": 20}],
    )
    assert mapping.lines[0].expense_account_id == 20
    with pytest.raises(ValidationError):
        ProcurementAPIntegrationIn(
            due_date="2026-11-30", payable_control_account_id=2,
            lines=[
                {"supplier_invoice_line_id": 10, "expense_account_id": 20},
                {"supplier_invoice_line_id": 10, "expense_account_id": 21},
            ],
        )


def test_accounting_completion_routes_are_registered():
    paths = set(app.openapi()["paths"])
    assert "/api/v1/accounting/cash-flow" in paths
    assert "/api/v1/accounting/statutory-tax-summary" in paths
    assert "/api/v1/accounting/procurement-invoices/{supplier_invoice_id}/integrate" in paths
    assert "/api/v1/accounting/credit-notes/{credit_note_id}/refund" in paths
    assert "/api/v1/accounting/refunds" in paths
    assert "/api/v1/accounting/fiscal-periods/{period_id}/year-end-close-preview" in paths
    assert "/api/v1/accounting/fiscal-periods/{period_id}/year-end-close" in paths


def test_year_end_close_requires_explicit_confirmation_code():
    payload = AccountingYearEndCloseIn(retained_earnings_account_id=4, confirmation_code="FY2026")
    assert payload.confirmation_code == "FY2026"
    with pytest.raises(ValidationError):
        AccountingYearEndCloseIn(retained_earnings_account_id=4, confirmation_code="")
