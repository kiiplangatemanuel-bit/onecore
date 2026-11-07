"""Safaricom Daraja M-Pesa STK Push collections and B2C refunds.

Callbacks are unauthenticated by Safaricom; every callback URL therefore carries
a high-entropy one-time token whose SHA-256 hash is stored against its intent.
No payment is settled from the initiation response.
"""
import base64
import hashlib
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db, SessionLocal
from app.core.models import (
    AuditEvent, MpesaPaymentIntent, MpesaRefundIntent, POSPayment,
    POSSale, POSRefund, POSReturn,
)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, can_access_branch

router = APIRouter(prefix="/api/v1/integrations/mpesa", tags=["M-Pesa"])
CENT = Decimal("0.01")


def normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif digits.startswith("7") or digits.startswith("1"):
        digits = "254" + digits
    if len(digits) != 12 or not digits.startswith("254") or digits[3] not in "17":
        raise ValueError("Use a valid Kenyan M-Pesa phone number, e.g. 2547XXXXXXXX")
    return digits


def stk_password(shortcode: str, passkey: str, timestamp: str) -> str:
    raw = f"{shortcode}{passkey}{timestamp}".encode()
    return base64.b64encode(raw).decode()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _enabled():
    required = (
        settings.mpesa_base_url, settings.mpesa_consumer_key,
        settings.mpesa_consumer_secret, settings.mpesa_shortcode,
        settings.mpesa_passkey, settings.mpesa_callback_url,
    )
    if not settings.integration_mpesa_enabled or not all(required):
        raise HTTPException(503, "M-Pesa integration is not enabled or its Daraja configuration is incomplete")


def _token(client: httpx.Client) -> str:
    response = client.get(
        urljoin(settings.mpesa_base_url.rstrip("/") + "/", "oauth/v1/generate?grant_type=client_credentials"),
        auth=(settings.mpesa_consumer_key, settings.mpesa_consumer_secret),
        timeout=20,
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise HTTPException(502, "Daraja OAuth response did not contain an access token")
    return token


def _post(path: str, payload: dict) -> dict:
    _enabled()
    try:
        with httpx.Client() as client:
            token = _token(client)
            response = client.post(
                urljoin(settings.mpesa_base_url.rstrip("/") + "/", path.lstrip("/")),
                json=payload, headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise HTTPException(502, "Unexpected Daraja response")
            return data
    except httpx.HTTPStatusError as exc:
        detail = "Daraja rejected the request"
        try:
            detail = exc.response.json().get("errorMessage") or exc.response.json().get("ResponseDescription") or detail
        except Exception:
            pass
        raise HTTPException(502, detail[:300]) from exc
    except httpx.RequestError as exc:
        raise HTTPException(503, "Could not reach Safaricom Daraja; retry after checking provider status") from exc


def _callback_url(path: str, token: str) -> str:
    base = settings.mpesa_callback_url.rstrip("/") + "/"
    return urljoin(base, f"{path.strip('/')}/{token}")


class STKPushIn(BaseModel):
    phone_number: str = Field(min_length=9, max_length=20)


class B2CRefundIn(BaseModel):
    phone_number: str = Field(min_length=9, max_length=20)


def _audit(db, org_id, actor_id, action, resource_type, resource_id, detail):
    db.add(AuditEvent(
        organization_id=org_id, actor_user_id=actor_id, action=action,
        resource_type=resource_type, resource_id=str(resource_id), detail=detail,
    ))


@router.post("/pos/sales/{sale_id}/payments/{payment_id}/stk-push")
def initiate_stk_push(sale_id: int, payment_id: int, payload: STKPushIn,
                      membership=Depends(active_membership), user=Depends(current_user),
                      db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    _enabled()
    sale = db.query(POSSale).filter_by(
        id=sale_id, organization_id=membership.organization_id, status="posted"
    ).first()
    if not sale or not can_access_branch(membership, sale.branch_id):
        raise HTTPException(404, "POS sale not found")
    payment = db.query(POSPayment).filter_by(
        id=payment_id, organization_id=membership.organization_id,
        sale_id=sale.id, method="mpesa",
    ).with_for_update().first()
    if not payment:
        raise HTTPException(404, "M-Pesa tender allocation not found")
    existing = db.query(MpesaPaymentIntent).filter_by(
        organization_id=membership.organization_id, payment_id=payment.id
    ).first()
    if existing:
        if existing.status in {"initiated", "pending", "success"}:
            return {"intent_id": existing.id, "status": existing.status,
                    "checkout_request_id": existing.checkout_request_id,
                    "message": "An M-Pesa request already exists for this tender"}
        raise HTTPException(409, "This tender already has a terminal M-Pesa attempt; create a new POS tender to retry")
    amount = Decimal(str(payment.amount))
    if amount != amount.quantize(Decimal("1")):
        raise HTTPException(422, "Daraja STK Push accepts whole KES amounts; split or adjust the tender to whole shillings")
    try:
        phone = normalize_phone(payload.phone_number)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    timestamp = _timestamp()
    callback_token = secrets.token_urlsafe(32)
    intent = MpesaPaymentIntent(
        organization_id=membership.organization_id, branch_id=sale.branch_id,
        payment_id=payment.id, phone_number=phone, amount=amount,
        callback_token_hash=hashlib.sha256(callback_token.encode()).hexdigest(),
        status="initiating",
    )
    db.add(intent)
    db.flush()
    shortcode = settings.mpesa_shortcode
    response = _post("mpesa/stkpush/v1/processrequest", {
        "BusinessShortCode": shortcode,
        "Password": stk_password(shortcode, settings.mpesa_passkey, timestamp),
        "Timestamp": timestamp, "TransactionType": "CustomerPayBillOnline",
        "Amount": int(amount), "PartyA": phone, "PartyB": shortcode,
        "PhoneNumber": phone, "CallBackURL": _callback_url("stk", callback_token),
        "AccountReference": f"OC-{sale.id}"[:12],
        "TransactionDesc": f"OneCore POS sale {sale.id}"[:13],
    })
    if response.get("ResponseCode") != "0" or not response.get("CheckoutRequestID"):
        intent.status = "failed"
        intent.result_description = str(response.get("ResponseDescription") or response.get("errorMessage") or "Daraja did not accept STK request")[:500]
        db.commit()
        raise HTTPException(502, intent.result_description)
    intent.merchant_request_id = str(response.get("MerchantRequestID") or "")[:100]
    intent.checkout_request_id = str(response["CheckoutRequestID"])[:100]
    intent.status = "pending"
    payment.status = "unsettled"
    _audit(db, membership.organization_id, user.id, "mpesa.stk.initiated",
           "pos_payment", payment.id, f"intent:{intent.id};amount:{amount};phone:{phone[-4:]}")
    db.commit()
    return {"intent_id": intent.id, "status": intent.status,
            "checkout_request_id": intent.checkout_request_id,
            "customer_message": response.get("CustomerMessage", "Check your phone to complete M-Pesa payment")}


def _stk_callback(db: Session, token: str, body: dict):
    digest = hashlib.sha256(token.encode()).hexdigest()
    intent = db.query(MpesaPaymentIntent).filter_by(callback_token_hash=digest).with_for_update().first()
    if not intent:
        return False
    callback = (body.get("Body") or {}).get("stkCallback") or {}
    checkout_id = str(callback.get("CheckoutRequestID") or "")
    if checkout_id != str(intent.checkout_request_id or ""):
        return False
    if intent.status == "success":
        return True
    code = callback.get("ResultCode")
    intent.result_code = str(code if code is not None else "")[:40]
    intent.result_description = str(callback.get("ResultDesc") or "")[:500]
    if code == 0:
        items = ((callback.get("CallbackMetadata") or {}).get("Item") or [])
        metadata = {str(item.get("Name")): item.get("Value") for item in items if isinstance(item, dict)}
        try:
            paid = Decimal(str(metadata.get("Amount"))).quantize(CENT)
        except Exception:
            return False
        if paid != Decimal(str(intent.amount)).quantize(CENT):
            intent.status = "exception"
            intent.result_description = "Callback amount does not match requested tender"
            db.commit()
            return True
        receipt = str(metadata.get("MpesaReceiptNumber") or "")
        if not receipt:
            intent.status = "exception"
            intent.result_description = "Successful callback did not include an M-Pesa receipt number"
            db.commit()
            return True
        payment = db.query(POSPayment).filter_by(
            id=intent.payment_id, organization_id=intent.organization_id
        ).with_for_update().first()
        if not payment:
            return False
        payment.status = "recorded"
        payment.provider_reference = receipt[:120]
        intent.mpesa_receipt_number = receipt[:40]
        intent.status = "success"
        intent.completed_at = datetime.now(timezone.utc)
        from app.api.accounting_pos import post_pos_source
        link = post_pos_source(db, intent.organization_id, intent.branch_id,
                               "sale", db.query(POSSale.id).filter_by(id=payment.sale_id).scalar(),
                               actor_user_id=None)
        _audit(db, intent.organization_id, None, "mpesa.stk.succeeded",
               "pos_payment", payment.id, f"receipt:{receipt};journal_link:{link.status}")
    else:
        intent.status = "failed"
        payment = db.query(POSPayment).filter_by(id=intent.payment_id).first()
        if payment:
            payment.status = "unsettled"
    db.commit()
    return True


@router.post("/callbacks/stk/{token}")
async def stk_callback(token: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid callback JSON")
    db = SessionLocal()
    try:
        if not _stk_callback(db, token, body):
            raise HTTPException(404, "Unknown or mismatched M-Pesa callback")
        return {"ResultCode": 0, "ResultDesc": "Accepted"}
    finally:
        db.close()


@router.post("/pos/returns/{return_id}/refunds/{refund_id}/b2c")
def initiate_b2c_refund(return_id: int, refund_id: int, payload: B2CRefundIn,
                        membership=Depends(active_membership), user=Depends(current_user),
                        db: Session = Depends(get_db)):
    require_permission(membership, "manage")
    _enabled()
    if not all((settings.mpesa_initiator_name, settings.mpesa_security_credential,
                settings.mpesa_b2c_result_url, settings.mpesa_b2c_timeout_url)):
        raise HTTPException(503, "M-Pesa B2C initiator, encrypted security credential and result/timeout URLs are required")
    result = db.query(POSReturn).filter_by(
        id=return_id, organization_id=membership.organization_id
    ).first()
    if not result or not can_access_branch(membership, result.branch_id):
        raise HTTPException(404, "POS return not found")
    refund = db.query(POSRefund).filter_by(
        id=refund_id, organization_id=membership.organization_id,
        return_id=result.id, method="mpesa",
    ).with_for_update().first()
    if not refund:
        raise HTTPException(404, "M-Pesa refund allocation not found")
    existing = db.query(MpesaRefundIntent).filter_by(
        organization_id=membership.organization_id, refund_id=refund.id
    ).first()
    if existing:
        return {"intent_id": existing.id, "status": existing.status,
                "conversation_id": existing.conversation_id,
                "message": "A disbursement request already exists; do not submit a duplicate refund"}
    amount = Decimal(str(refund.amount))
    if amount != amount.quantize(Decimal("1")):
        raise HTTPException(422, "Daraja B2C accepts whole KES amounts; this refund requires manual handling")
    try:
        phone = normalize_phone(payload.phone_number)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    callback_token = secrets.token_urlsafe(32)
    intent = MpesaRefundIntent(
        organization_id=membership.organization_id, branch_id=result.branch_id,
        refund_id=refund.id, phone_number=phone, amount=amount,
        callback_token_hash=hashlib.sha256(callback_token.encode()).hexdigest(),
        status="initiating",
    )
    db.add(intent)
    db.flush()
    base = settings.mpesa_base_url.rstrip("/") + "/"
    response = _post("mpesa/b2c/v1/paymentrequest", {
        "InitiatorName": settings.mpesa_initiator_name,
        "SecurityCredential": settings.mpesa_security_credential,
        "CommandID": "BusinessPayment", "Amount": int(amount),
        "PartyA": settings.mpesa_shortcode, "PartyB": phone,
        "Remarks": f"OneCore POS refund {result.id}"[:100],
        "QueueTimeOutURL": urljoin(settings.mpesa_b2c_timeout_url.rstrip("/") + "/", callback_token),
        "ResultURL": urljoin(settings.mpesa_b2c_result_url.rstrip("/") + "/", callback_token),
        "Occasion": f"POS-{result.id}"[:20],
    })
    if response.get("ResponseCode") != "0":
        intent.status = "failed"
        intent.result_description = str(response.get("ResponseDescription") or response.get("errorMessage") or "Daraja rejected B2C request")[:500]
        db.commit()
        raise HTTPException(502, intent.result_description)
    intent.conversation_id = str(response.get("ConversationID") or "")[:100]
    intent.originator_conversation_id = str(response.get("OriginatorConversationID") or "")[:100]
    intent.status = "pending"
    refund.status = "pending"
    _audit(db, membership.organization_id, user.id, "mpesa.b2c.initiated",
           "pos_refund", refund.id, f"intent:{intent.id};amount:{amount};phone:{phone[-4:]}")
    db.commit()
    return {"intent_id": intent.id, "status": intent.status,
            "conversation_id": intent.conversation_id,
            "response_description": response.get("ResponseDescription")}


def _b2c_callback(db: Session, token: str, body: dict, timeout=False):
    digest = hashlib.sha256(token.encode()).hexdigest()
    intent = db.query(MpesaRefundIntent).filter_by(callback_token_hash=digest).with_for_update().first()
    if not intent:
        return False
    if intent.status == "success":
        return True
    result = body.get("Result") or body
    code = result.get("ResultCode")
    intent.result_code = str(code if code is not None else "")[:40]
    intent.result_description = str(result.get("ResultDesc") or ("Provider timeout" if timeout else ""))[:500]
    if not timeout and code == 0:
        params = ((result.get("ResultParameters") or {}).get("ResultParameter") or [])
        metadata = {str(item.get("Key")): item.get("Value") for item in params if isinstance(item, dict)}
        receipt = str(metadata.get("TransactionReceipt") or "")
        refund = db.query(POSRefund).filter_by(
            id=intent.refund_id, organization_id=intent.organization_id
        ).with_for_update().first()
        if not refund or not receipt:
            intent.status = "exception"
            intent.result_description = "Successful B2C callback is missing its refund record or transaction receipt"
            db.commit()
            return True
        refund.status = "recorded"
        refund.provider_reference = receipt[:120]
        intent.mpesa_receipt_number = receipt[:40]
        intent.status = "success"
        intent.completed_at = datetime.now(timezone.utc)
        from app.api.accounting_pos import post_pos_source
        ret = db.query(POSReturn).filter_by(id=refund.return_id, organization_id=intent.organization_id).first()
        if ret:
            post_pos_source(db, intent.organization_id, intent.branch_id, "return", ret.id, actor_user_id=None)
        _audit(db, intent.organization_id, None, "mpesa.b2c.succeeded",
               "pos_refund", refund.id, f"receipt:{receipt}")
    else:
        intent.status = "timeout" if timeout else "failed"
        # Keep refund pending; no money movement is claimed until confirmed success.
    db.commit()
    return True


@router.post("/callbacks/b2c/result/{token}")
async def b2c_result_callback(token: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid callback JSON")
    db = SessionLocal()
    try:
        if not _b2c_callback(db, token, body):
            raise HTTPException(404, "Unknown M-Pesa B2C result callback")
        return {"ResultCode": 0, "ResultDesc": "Accepted"}
    finally:
        db.close()


@router.post("/callbacks/b2c/timeout/{token}")
async def b2c_timeout_callback(token: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid callback JSON")
    db = SessionLocal()
    try:
        if not _b2c_callback(db, token, body, timeout=True):
            raise HTTPException(404, "Unknown M-Pesa B2C timeout callback")
        return {"ResultCode": 0, "ResultDesc": "Accepted"}
    finally:
        db.close()


@router.get("/pos/sales/{sale_id}/payments")
def mpesa_payment_status(sale_id: int, membership=Depends(active_membership),
                         db: Session = Depends(get_db)):
    require_permission(membership, "read")
    sale = db.query(POSSale).filter_by(id=sale_id, organization_id=membership.organization_id).first()
    if not sale or not can_access_branch(membership, sale.branch_id):
        raise HTTPException(404, "POS sale not found")
    rows = db.query(MpesaPaymentIntent).join(
        POSPayment, POSPayment.id == MpesaPaymentIntent.payment_id
    ).filter(MpesaPaymentIntent.organization_id == membership.organization_id,
             POSPayment.sale_id == sale.id).order_by(MpesaPaymentIntent.id).all()
    return [{"intent_id": row.id, "payment_id": row.payment_id, "amount": str(row.amount),
             "phone_number": row.phone_number, "status": row.status,
             "receipt": row.mpesa_receipt_number, "result_description": row.result_description}
            for row in rows]
