"""Consent-safe email, SMS and WhatsApp provider adapters."""
import smtplib
from email.message import EmailMessage
import httpx
from urllib.parse import urlsplit
from fastapi import HTTPException
from app.core.config import settings

def build_unsubscribe_url(token, public_base_url):
    base=(public_base_url or "").strip().rstrip("/")
    parsed=urlsplit(base)
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(503,"CRM_PUBLIC_BASE_URL must be configured with a public HTTPS URL")
    return f"{base}/api/v1/crm/unsubscribe/{token}"

def send_campaign_message(channel, address, subject, message, idempotency_key, unsubscribe_url=None):
    if channel == "email":
        if not (settings.integration_email_enabled and settings.email_host and settings.email_from):
            raise HTTPException(503, "Email delivery is not configured")
        mail=EmailMessage(); mail["From"]=settings.email_from; mail["To"]=address
        mail["Subject"]=subject or "A message from us"; mail["X-OneCore-Idempotency-Key"]=idempotency_key
        body=message + (("\n\nUnsubscribe: "+unsubscribe_url) if unsubscribe_url else "")
        mail.set_content(body)
        if unsubscribe_url:
            mail["List-Unsubscribe"]=f"<{unsubscribe_url}>"
            mail["List-Unsubscribe-Post"]="List-Unsubscribe=One-Click"
        with smtplib.SMTP(settings.email_host, settings.email_port, timeout=20) as server:
            server.starttls()
            if settings.email_username: server.login(settings.email_username, settings.email_password)
            server.send_message(mail)
        return {"provider_message_id":idempotency_key}
    if channel=="sms":
        enabled,url,key,sender=settings.integration_sms_enabled,settings.sms_base_url,settings.sms_api_key,settings.sms_sender_id
    elif channel=="whatsapp":
        enabled,url,key,sender=settings.integration_whatsapp_enabled,settings.whatsapp_base_url,settings.whatsapp_token,settings.whatsapp_phone_number_id
    else: raise HTTPException(422,"Unsupported campaign channel")
    if not (enabled and url and key): raise HTTPException(503,f"{channel.upper()} delivery is not configured")
    response=httpx.post(url,json={"to":address,"message":message,"subject":subject,"sender":sender,
        "idempotency_key":idempotency_key,"unsubscribe_url":unsubscribe_url},
        headers={"Authorization":f"Bearer {key}","Idempotency-Key":idempotency_key},timeout=25)
    response.raise_for_status(); data=response.json() if response.content else {}
    return {"provider_message_id":str(data.get("message_id") or data.get("id") or idempotency_key)}
