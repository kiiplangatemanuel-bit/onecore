from datetime import date
from decimal import Decimal

from pydantic import ValidationError
import pytest

from app.api.sacco_finance import (
    StandingOrderIn, CollectionIn, ReconcileIn, RestructureIn,
    DividendIn, ProvisionPolicyIn, JournalPostIn,
)
from app.core.models import Base, SaccoFinanceRecord
from app.main import app


def test_sacco_finance_model_and_migration_table_registered():
    assert "sacco_finance_records" in Base.metadata.tables
    assert SaccoFinanceRecord.__tablename__ == "sacco_finance_records"


def test_standing_order_validation():
    item = StandingOrderIn(account_id=1, amount=Decimal("100.00"),
        frequency="monthly", next_run=date(2026, 12, 1))
    assert item.frequency == "monthly"
    with pytest.raises(ValidationError):
        StandingOrderIn(account_id=1, amount=Decimal("0"), frequency="daily",
            next_run=date(2026, 12, 1))


def test_collection_and_reconciliation_validation():
    item = CollectionIn(provider="mpesa", external_reference="MPESA-12345",
        amount=Decimal("200.00"), member_id=1, target_type="savings",
        target_id=2, value_date=date(2026, 11, 8))
    assert item.currency == "KES"
    with pytest.raises(ValidationError):
        ReconcileIn(collection_id=1, statement_reference="x",
            statement_amount=Decimal("1.001"), idempotency_key="bad-key")


def test_restructure_dividend_and_provision_policy_validation():
    assert RestructureIn(new_term_months=24, first_due_date=date(2026, 12, 1),
        reason="Member income changed").new_term_months == 24
    assert DividendIn(pool_amount=Decimal("10000.00"), financial_year=2026,
        idempotency_key="dividend-run-2026").financial_year == 2026
    with pytest.raises(ValidationError):
        ProvisionPolicyIn(rate_1_30=Decimal("101"), rate_31_60=10,
            rate_61_90=25, rate_over_90=50)


def test_accounting_post_source_allowlist():
    assert JournalPostIn(source_type="loan_repayment", source_id=1,
        debit_account_id=2, credit_account_id=3, entry_date=date(2026, 11, 8),
        memo="Post loan repayment").source_type == "loan_repayment"
    with pytest.raises(ValidationError):
        JournalPostIn(source_type="arbitrary", source_id=1, debit_account_id=2,
            credit_account_id=3, entry_date=date(2026, 11, 8), memo="Invalid source")


def test_sacco_finance_api_routes_are_registered():
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/v1/sacco/finance/standing-orders",
        "/api/v1/sacco/finance/standing-orders/run",
        "/api/v1/sacco/finance/collections",
        "/api/v1/sacco/finance/collections/reconcile",
        "/api/v1/sacco/finance/loans/{loan_id}/restructure",
        "/api/v1/sacco/finance/restructures/{request_id}/decision",
        "/api/v1/sacco/finance/loans/{loan_id}/settlement-quote",
        "/api/v1/sacco/finance/loans/{loan_id}/refinance",
        "/api/v1/sacco/finance/refinances/{request_id}/decision",
        "/api/v1/sacco/finance/members/{member_id}/statement",
        "/api/v1/sacco/finance/members/{member_id}/statement.csv",
        "/api/v1/sacco/finance/dividends/allocate",
        "/api/v1/sacco/finance/shares/reconcile",
        "/api/v1/sacco/finance/loans/provisioning",
        "/api/v1/sacco/finance/accounting/post",
        "/api/v1/sacco/finance/arrears/notifications/queue",
        "/api/v1/sacco/finance/reports/regulatory",
    }
    assert expected.issubset(paths)
