from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.models import AccountingAccount, AccountingJournal, AccountingJournalLine
from app.core.schemas import AccountingAccountIn, AccountingJournalIn
from app.services.accounting import validate_journal_lines
from app.main import app


def test_journal_requires_balanced_debits_and_credits():
    payload = AccountingJournalIn(
        entry_date="2026-11-07",
        lines=[
            {"account_id": 1, "debit": "100.00", "credit": "0"},
            {"account_id": 2, "debit": "0", "credit": "100.00"},
        ],
    )
    assert validate_journal_lines(payload.lines) == (Decimal("100.00"), Decimal("100.00"))


def test_journal_rejects_unbalanced_amounts():
    lines = [
        type("Line", (), {"debit": Decimal("100"), "credit": Decimal("0")})(),
        type("Line", (), {"debit": Decimal("0"), "credit": Decimal("99")})(),
    ]
    with pytest.raises(HTTPException) as exc:
        validate_journal_lines(lines)
    assert exc.value.status_code == 422


def test_journal_rejects_line_with_both_debit_and_credit():
    lines = [
        type("Line", (), {"debit": Decimal("10"), "credit": Decimal("10")})(),
        type("Line", (), {"debit": Decimal("0"), "credit": Decimal("20")})(),
    ]
    with pytest.raises(HTTPException) as exc:
        validate_journal_lines(lines)
    assert exc.value.status_code == 422


def test_chart_of_accounts_contract_limits_account_type():
    account = AccountingAccountIn(code="1000", name="Cash", account_type="asset")
    assert account.account_type == "asset"
    with pytest.raises(ValidationError):
        AccountingAccountIn(code="1000", name="Cash", account_type="unknown")


def test_accounting_tables_and_routes_exist():
    assert AccountingAccount.__tablename__ == "accounting_accounts"
    assert AccountingJournal.__tablename__ == "accounting_journals"
    assert AccountingJournalLine.__tablename__ == "accounting_journal_lines"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/accounting/accounts" in paths
    assert "/api/v1/accounting/journals" in paths
    assert "/api/v1/accounting/trial-balance" in paths


def test_accounting_subledger_reconciliation_route_contract():
    paths = app.openapi()["paths"]
    endpoint = "/api/v1/accounting/subledger-reconciliation"
    assert endpoint in paths
    params = {item["name"] for item in paths[endpoint]["get"]["parameters"]}
    assert {"invoice_type", "as_of"} <= params


def test_accounting_workspace_exposes_subledger_reconciliation():
    from pathlib import Path
    page = Path(__file__).resolve().parents[1] / "app" / "web" / "accounting.html"
    html = page.read_text(encoding="utf-8")
    assert 'id="subledgerReconciliation"' in html
    assert 'id="subledgerResult"' in html
    assert "/accounting/subledger-reconciliation" in html


def test_accounting_financial_statements_route_contract():
    paths = app.openapi()["paths"]
    endpoint = "/api/v1/accounting/financial-statements"
    assert endpoint in paths
    params = {item["name"] for item in paths[endpoint]["get"]["parameters"]}
    assert {"statement_type", "start_date", "end_date"} <= params


def test_accounting_financial_statements_workspace_controls():
    from pathlib import Path
    page = Path(__file__).resolve().parents[1] / "app" / "web" / "accounting.html"
    html = page.read_text(encoding="utf-8")
    assert 'id="financialStatementForm"' in html
    assert 'id="financialStatementResult"' in html
    assert "/accounting/financial-statements" in html


def test_accounting_year_end_close_routes_and_confirmation_contract():
    paths = app.openapi()["paths"]
    preview = "/api/v1/accounting/fiscal-periods/{period_id}/year-end-close-preview"
    close = "/api/v1/accounting/fiscal-periods/{period_id}/year-end-close"
    assert preview in paths and "get" in paths[preview]
    assert close in paths and "post" in paths[close]
    from app.core.schemas import AccountingYearEndCloseIn
    payload = AccountingYearEndCloseIn(
        retained_earnings_account_id=7, confirmation_code="FY2026")
    assert payload.confirmation_code == "FY2026"
    with pytest.raises(ValidationError):
        AccountingYearEndCloseIn(retained_earnings_account_id=0, confirmation_code="FY")


def test_accounting_workspace_exposes_year_end_close_controls():
    from pathlib import Path
    page = Path(__file__).resolve().parents[1] / "app" / "web" / "accounting.html"
    html = page.read_text(encoding="utf-8")
    assert 'id="yearEndPreviewForm"' in html
    assert 'id="yearEndPostForm"' in html
    assert "/year-end-close-preview" in html
    assert "/year-end-close" in html


def test_accounting_financial_statements_route_contract():
    paths = app.openapi()["paths"]
    endpoint = "/api/v1/accounting/financial-statements"
    assert endpoint in paths
    params = {item["name"] for item in paths[endpoint]["get"]["parameters"]}
    assert {"statement_type", "start_date", "end_date"} <= params


def test_accounting_financial_statements_workspace_controls():
    from pathlib import Path
    page = Path(__file__).resolve().parents[1] / "app" / "web" / "accounting.html"
    html = page.read_text(encoding="utf-8")
    assert 'id="financialStatementForm"' in html
    assert 'id="financialStatementResult"' in html
    assert "/accounting/financial-statements" in html


def test_accounting_extended_reporting_and_refund_routes_are_registered():
    paths = set(app.openapi()["paths"])
    assert "/api/v1/accounting/statutory-tax-summary" in paths
    assert "/api/v1/accounting/cash-flow" in paths
    assert "/api/v1/accounting/refunds" in paths
    assert "/api/v1/accounting/invoices/{invoice_id}/refunds" in paths
    assert "/api/v1/procurement/supplier-invoices/{supplier_invoice_id}/post-to-accounting" in paths


def test_accounting_cash_flow_classification_is_validated():
    valid = AccountingAccountIn(code="1010", name="Main bank", account_type="asset",
        cash_flow_category="cash_equivalent")
    assert valid.cash_flow_category == "cash_equivalent"
    with pytest.raises(ValidationError):
        AccountingAccountIn(code="1011", name="Bad category", account_type="asset",
            cash_flow_category="miscellaneous")


def test_accounting_refund_requires_idempotency_and_positive_amount():
    from app.core.schemas import AccountingRefundIn
    payload = AccountingRefundIn(amount="25.00", payment_account_id=1,
        refund_date="2026-11-07", idempotency_key="refund-key-001")
    assert payload.amount == Decimal("25.00")
    with pytest.raises(ValidationError):
        AccountingRefundIn(amount="0", payment_account_id=1,
            refund_date="2026-11-07", idempotency_key="refund-key-001")


def test_accounting_workspace_exposes_tax_cashflow_and_refund_controls():
    from pathlib import Path
    page = Path(__file__).resolve().parents[1] / "app" / "web" / "accounting.html"
    source = page.read_text(encoding="utf-8")
    assert 'id="taxSummaryForm"' in source
    assert 'id="cashFlowForm"' in source
    assert 'id="refundForm"' in source
    assert 'id="procurementApForm"' in source
