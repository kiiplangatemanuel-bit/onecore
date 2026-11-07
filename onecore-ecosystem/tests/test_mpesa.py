from base64 import b64decode
from decimal import Decimal
import hashlib
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest
from fastapi import HTTPException

from app.api.mpesa import normalize_phone, stk_password
from app.core.database import Base
from app.core.models import (AuditEvent, MpesaPaymentIntent, MpesaRefundIntent, POSPayment, POSSale, POSRefund, POSReturn)
from app.core.schemas import POSPaymentIn, POSRefundIn
from app.main import app


def test_mpesa_phone_normalization_accepts_common_kenyan_formats():
    assert normalize_phone("0712345678") == "254712345678"
    assert normalize_phone("+254 712 345 678") == "254712345678"
    assert normalize_phone("112345678") == "254112345678"


@pytest.mark.parametrize("phone", ["123", "254012345678", "25471234567", "254812345678"])
def test_mpesa_phone_normalization_rejects_invalid_numbers(phone):
    with pytest.raises(ValueError):
        normalize_phone(phone)


def test_stk_password_uses_shortcode_passkey_and_timestamp():
    expected = b"174379secretpasskey20260101120000"
    assert b64decode(stk_password("174379", "secretpasskey", "20260101120000")) == expected


def test_mpesa_intent_models_and_api_routes_are_registered():
    assert MpesaPaymentIntent.__tablename__ == "mpesa_payment_intents"
    assert MpesaRefundIntent.__tablename__ == "mpesa_refund_intents"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/integrations/mpesa/pos/sales/{sale_id}/payments/{payment_id}/stk-push" in paths
    assert "/api/v1/integrations/mpesa/callbacks/stk/{token}" in paths
    assert "/api/v1/integrations/mpesa/pos/returns/{return_id}/refunds/{refund_id}/b2c" in paths
    assert "/api/v1/integrations/mpesa/callbacks/b2c/result/{token}" in paths
    assert "/api/v1/integrations/mpesa/callbacks/b2c/timeout/{token}" in paths
    assert "/api/v1/integrations/mpesa/pos/sales/{sale_id}/payments" in paths
    assert "/api/v1/integrations/mpesa/pos/sales/{sale_id}/refunds" in paths


def test_pos_workspace_exposes_m_pesa_collection_and_refund_controls():
    from pathlib import Path
    html = Path(__file__).resolve().parents[1] / "app" / "web" / "pos.html"
    source = html.read_text(encoding="utf-8")
    assert 'value="mpesa"' in source or '<option>mpesa</option>' in source
    assert 'name="mpesa_phone"' in source
    assert 'name="refund_phone"' in source
    assert "/stk-push" in source
    assert "/b2c" in source
    assert "restore pending M-Pesa" not in source
    assert "/refunds" in source
    assert "Outcome is uncertain" in source



def test_pos_payment_and_refund_schemas_accept_mpesa_tender():
    payment = POSPaymentIn(method="mpesa", amount="125.00")
    refund = POSRefundIn(method="mpesa", amount="125.00")
    assert payment.method == "mpesa"
    assert refund.method == "mpesa"


def test_pos_workspace_keeps_safe_retry_for_mpesa_payout():
    from pathlib import Path
    html = Path(__file__).resolve().parents[1] / "app" / "web" / "pos.html"
    source = html.read_text(encoding="utf-8")
    assert "Retry the same refund; do not create another return." in source
    assert "Check / retry after Safaricom responds." in source



def _mpesa_test_session():
    engine = create_engine("sqlite://")
    tables = [
        AuditEvent.__table__, POSSale.__table__, POSPayment.__table__,
        MpesaPaymentIntent.__table__, POSReturn.__table__, POSRefund.__table__,
        MpesaRefundIntent.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    return sessionmaker(bind=engine)()


def test_successful_stk_callback_settles_tender_and_posts_journal_once(monkeypatch):
    import app.api.accounting_pos as accounting_pos
    from app.api.mpesa import _stk_callback
    db = _mpesa_test_session()
    sale = POSSale(
        id=7, organization_id=1, branch_id="branch-1", shift_id=2,
        cashier_user_id=10, client_transaction_id="txn-00000007",
        request_hash="a" * 64, total_amount=Decimal("100.00"),
        currency="KES", status="posted",
    )
    payment = POSPayment(
        id=8, organization_id=1, sale_id=7, method="mpesa",
        amount=Decimal("100.00"), status="unsettled",
    )
    token = "callback-secret"
    intent = MpesaPaymentIntent(
        id=9, organization_id=1, branch_id="branch-1", payment_id=8,
        phone_number="254712345678", amount=Decimal("100.00"),
        checkout_request_id="ws_CO_123", callback_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        status="pending",
    )
    db.add_all([sale, payment, intent])
    db.commit()
    posted = []
    monkeypatch.setattr(accounting_pos, "post_pos_source",
                        lambda *args, **kwargs: (posted.append((args, kwargs)) or SimpleNamespace(status="posted")))
    body = {"Body": {"stkCallback": {
        "CheckoutRequestID": "ws_CO_123", "ResultCode": 0, "ResultDesc": "Success",
        "CallbackMetadata": {"Item": [
            {"Name": "Amount", "Value": 100},
            {"Name": "MpesaReceiptNumber", "Value": "QAB123XYZ"},
            {"Name": "PhoneNumber", "Value": 254712345678},
        ]},
    }}}
    assert _stk_callback(db, token, body) is True
    db.refresh(payment)
    db.refresh(intent)
    assert payment.status == "recorded"
    assert payment.provider_reference == "QAB123XYZ"
    assert intent.status == "success"
    assert len(posted) == 1
    assert _stk_callback(db, token, body) is True
    assert len(posted) == 1
    db.close()


def test_successful_b2c_callback_records_refund_only_after_receipt(monkeypatch):
    import app.api.accounting_pos as accounting_pos
    from app.api.mpesa import _b2c_callback
    db = _mpesa_test_session()
    returned = POSReturn(
        id=21, organization_id=1, sale_id=7, branch_id="branch-1",
        client_return_id="return-000021", request_hash="b" * 64,
        reason="Customer return", refund_total=Decimal("50.00"), created_by=10,
    )
    refund = POSRefund(
        id=22, organization_id=1, return_id=21, method="mpesa",
        amount=Decimal("50.00"), status="pending",
    )
    token = "b2c-callback-secret"
    intent = MpesaRefundIntent(
        id=23, organization_id=1, branch_id="branch-1", refund_id=22,
        phone_number="254712345678", amount=Decimal("50.00"),
        conversation_id="AG_123", callback_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        status="pending",
    )
    db.add_all([returned, refund, intent])
    db.commit()
    posted = []
    monkeypatch.setattr(accounting_pos, "post_pos_source",
                        lambda *args, **kwargs: (posted.append((args, kwargs)) or SimpleNamespace(status="posted")))
    body = {"Result": {
        "ConversationID": "AG_123", "ResultCode": 0, "ResultDesc": "Success",
        "ResultParameters": {"ResultParameter": [
            {"Key": "TransactionReceipt", "Value": "QAB123B2C"},
            {"Key": "TransactionAmount", "Value": 50},
        ]},
    }}
    assert _b2c_callback(db, token, body) is True
    db.refresh(refund)
    db.refresh(intent)
    assert refund.status == "recorded"
    assert refund.provider_reference == "QAB123B2C"
    assert intent.status == "success"
    assert len(posted) == 1
    db.close()



def test_b2c_success_callback_requires_amount_receipt_and_matching_conversation(monkeypatch):
    from app.api.mpesa import _b2c_callback
    db = _mpesa_test_session()
    returned = POSReturn(
        id=31, organization_id=1, sale_id=7, branch_id="branch-1",
        client_return_id="return-000031", request_hash="c" * 64,
        reason="Customer return", refund_total=Decimal("25.00"), created_by=10,
    )
    refund = POSRefund(
        id=32, organization_id=1, return_id=31, method="mpesa",
        amount=Decimal("25.00"), status="pending",
    )
    token = "strict-b2c-callback"
    intent = MpesaRefundIntent(
        id=33, organization_id=1, branch_id="branch-1", refund_id=32,
        phone_number="254712345678", amount=Decimal("25.00"),
        conversation_id="AG_331", originator_conversation_id="OR_331",
        callback_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        status="pending",
    )
    db.add_all([returned, refund, intent])
    db.commit()
    # A callback for another provider conversation must not mutate the refund.
    assert _b2c_callback(db, token, {"Result": {"ConversationID": "AG_WRONG", "ResultCode": 0}}) is False
    # Success without the transaction amount is not proof of the requested payout.
    body = {"Result": {
        "ConversationID": "AG_331", "ResultCode": 0, "ResultDesc": "Success",
        "ResultParameters": {"ResultParameter": [
            {"Key": "TransactionReceipt", "Value": "QAB331B2C"},
        ]},
    }}
    assert _b2c_callback(db, token, body) is True
    db.refresh(refund)
    db.refresh(intent)
    assert refund.status == "pending"
    assert refund.provider_reference == ""
    assert intent.status == "exception"
    assert "amount is missing" in intent.result_description
    db.close()


def test_successful_stk_callback_rejects_duplicate_provider_receipt(monkeypatch):
    from app.api.mpesa import _stk_callback
    db = _mpesa_test_session()
    sale = POSSale(
        id=41, organization_id=1, branch_id="branch-1", shift_id=2,
        cashier_user_id=10, client_transaction_id="txn-00000041",
        request_hash="d" * 64, total_amount=Decimal("100.00"),
        currency="KES", status="posted",
    )
    payment = POSPayment(
        id=42, organization_id=1, sale_id=41, method="mpesa",
        amount=Decimal("100.00"), status="unsettled",
    )
    duplicate = POSPayment(
        id=43, organization_id=1, sale_id=41, method="mpesa",
        amount=Decimal("100.00"), status="recorded", provider_reference="QABDUPLICATE",
    )
    token = "duplicate-stk-receipt"
    intent = MpesaPaymentIntent(
        id=44, organization_id=1, branch_id="branch-1", payment_id=42,
        phone_number="254712345678", amount=Decimal("100.00"),
        checkout_request_id="ws_CO_441",
        callback_token_hash=hashlib.sha256(token.encode()).hexdigest(), status="pending",
    )
    db.add_all([sale, payment, duplicate, intent])
    db.commit()
    body = {"Body": {"stkCallback": {
        "CheckoutRequestID": "ws_CO_441", "ResultCode": 0, "ResultDesc": "Success",
        "CallbackMetadata": {"Item": [
            {"Name": "Amount", "Value": 100},
            {"Name": "MpesaReceiptNumber", "Value": "QABDUPLICATE"},
            {"Name": "PhoneNumber", "Value": 254712345678},
        ]},
    }}}
    assert _stk_callback(db, token, body) is True
    db.refresh(payment)
    db.refresh(intent)
    assert payment.status == "unsettled"
    assert intent.status == "exception"
    db.close()
