from base64 import b64decode

import pytest
from fastapi import HTTPException

from app.api.mpesa import normalize_phone, stk_password
from app.core.models import MpesaPaymentIntent, MpesaRefundIntent
from app.main import app


def test_mpesa_phone_normalization_accepts_common_kenyan_formats():
    assert normalize_phone("0712345678") == "254712345678"
    assert normalize_phone("+254 712 345 678") == "254712345678"
    assert normalize_phone("112345678") == "254112345678"


@pytest.mark.parametrize("phone", ["123", "0700000000", "254012345678", "25471234567", "254812345678"])
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


def test_pos_workspace_exposes_m_pesa_collection_and_refund_controls():
    from pathlib import Path
    html = Path(__file__).resolve().parents[1] / "app" / "web" / "pos.html"
    source = html.read_text(encoding="utf-8")
    assert 'value="mpesa"' in source or '<option>mpesa</option>' in source
    assert 'name="mpesa_phone"' in source
    assert 'name="refund_phone"' in source
    assert "/stk-push" in source
    assert "/b2c" in source
