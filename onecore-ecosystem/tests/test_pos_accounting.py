from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.accounting_pos import POSAccountingMappingIn, _line, _money
from app.core.models import POSAccountingMapping, POSAccountingLink
from app.main import app


def test_pos_accounting_models_and_routes_are_registered():
    assert POSAccountingMapping.__tablename__ == "pos_accounting_mappings"
    assert POSAccountingLink.__tablename__ == "pos_accounting_links"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/accounting/pos-mapping" in paths
    assert "/api/v1/accounting/pos-integrations" in paths
    assert "/api/v1/accounting/pos-integrations/post-pending" in paths


def test_pos_accounting_mapping_requires_all_control_accounts():
    mapping = POSAccountingMappingIn(
        cash_account_id=1, card_clearing_account_id=2,
        bank_clearing_account_id=3, credit_receivable_account_id=4,
        sales_revenue_account_id=5, sales_discount_account_id=6,
        output_tax_account_id=7, sales_returns_account_id=8,
    )
    assert mapping.cash_account_id == 1
    with pytest.raises(Exception):
        POSAccountingMappingIn(
            cash_account_id=1, card_clearing_account_id=2,
            bank_clearing_account_id=3, credit_receivable_account_id=4,
            sales_revenue_account_id=5, sales_discount_account_id=6,
        )


def test_pos_journal_amounts_are_rounded_and_zero_lines_omitted():
    assert _money("10.005") == Decimal("10.01")
    lines = []
    _line(lines, 10, debit="12.345", description="cash")
    _line(lines, 11, credit="12.345", description="revenue")
    _line(lines, 12, debit="0", description="zero")
    assert lines == [
        (10, Decimal("12.35"), Decimal("0.00"), "cash"),
        (11, Decimal("0.00"), Decimal("12.35"), "revenue"),
    ]


def test_pos_journal_line_rejects_double_sided_and_negative_amounts():
    with pytest.raises(ValueError):
        _line([], 1, debit="1.00", credit="1.00")
    with pytest.raises(ValueError):
        _line([], 1, debit="-1.00")
