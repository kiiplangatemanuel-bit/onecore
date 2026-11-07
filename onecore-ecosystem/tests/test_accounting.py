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
