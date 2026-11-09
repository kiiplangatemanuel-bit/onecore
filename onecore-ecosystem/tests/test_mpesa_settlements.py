from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api.mpesa_settlements import SettlementEntry, _match_entry


class _Query:
    def __init__(self, row):
        self.row = row
    def filter_by(self, **kwargs):
        return self
    def one_or_none(self):
        return self.row


class _DB:
    def __init__(self, payment=None, refund=None):
        self.payment, self.refund = payment, refund
    def query(self, model):
        name = getattr(model, "__name__", "")
        return _Query(self.payment if name == "MpesaPaymentIntent" else self.refund)


def _entry(amount="250.00", kind="collection"):
    return SettlementEntry(
        receipt_number="QAB1234567", transaction_type=kind,
        transaction_at=datetime(2026, 11, 9, tzinfo=timezone.utc),
        amount=Decimal(amount),
    )


def test_collection_statement_line_matches_only_confirmed_receipt_and_exact_amount():
    row = SimpleNamespace(id=1, amount=Decimal("250.00"))
    kind, found, expected, status, detail = _match_entry(_DB(payment=row), 7, _entry())
    assert (kind, found.id, expected, status, detail) == ("collection", 1, Decimal("250.00"), "matched", "")


def test_payout_statement_line_matches_confirmed_refund():
    row = SimpleNamespace(id=2, amount=Decimal("90.00"))
    kind, found, expected, status, _ = _match_entry(_DB(refund=row), 7, _entry("90.00", "payout"))
    assert kind == "payout" and found.id == 2 and status == "matched"


def test_statement_amount_mismatch_is_exception_not_silent_match():
    row = SimpleNamespace(id=3, amount=Decimal("250.00"))
    kind, found, expected, status, detail = _match_entry(_DB(payment=row), 7, _entry("249.00"))
    assert status == "amount_mismatch"
    assert expected == Decimal("250.00")
    assert "differs" in detail


def test_unknown_receipt_is_unmatched():
    kind, found, expected, status, detail = _match_entry(_DB(), 7, _entry())
    assert found is None and expected is None and status == "unmatched"
    assert "No successful" in detail


def test_statement_entry_requires_timezone_and_token_receipt():
    with pytest.raises(ValueError):
        SettlementEntry(receipt_number="QAB1234567", transaction_type="collection",
                        transaction_at=datetime(2026, 11, 9), amount=Decimal("1"))
    with pytest.raises(ValueError):
        SettlementEntry(receipt_number="bad receipt", transaction_type="collection",
                        transaction_at=datetime(2026, 11, 9, tzinfo=timezone.utc), amount=Decimal("1"))
