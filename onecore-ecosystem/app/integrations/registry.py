from app.core.config import settings

PROVIDERS = {
    "mpesa": {"enabled": settings.integration_mpesa_enabled, "configured": bool(settings.mpesa_base_url and settings.mpesa_consumer_key and settings.mpesa_consumer_secret)},
    "etims": {"enabled": settings.integration_etims_enabled, "configured": bool(settings.etims_base_url and settings.etims_client_id and settings.etims_client_secret)},
    "sha": {"enabled": settings.integration_sha_enabled, "configured": bool(settings.sha_base_url and settings.sha_client_id and settings.sha_client_secret)},
    "bank": {"enabled": settings.integration_bank_enabled, "configured": bool(settings.bank_base_url and settings.bank_client_id and settings.bank_client_secret)},
    "email": {"enabled": settings.integration_email_enabled, "configured": bool(settings.email_host and settings.email_from)},
    "sms": {"enabled": settings.integration_sms_enabled, "configured": bool(settings.sms_base_url and settings.sms_api_key)},
    "whatsapp": {"enabled": settings.integration_whatsapp_enabled, "configured": bool(settings.whatsapp_base_url and settings.whatsapp_token)},
    "ai": {"enabled": settings.integration_ai_enabled, "configured": bool(settings.ai_base_url and settings.ai_api_key)},
    "object_storage": {"enabled": settings.integration_object_storage_enabled, "configured": bool(settings.s3_bucket and settings.s3_access_key_id and settings.s3_secret_access_key)},
}

def public_provider_status():
    return {name: {"enabled": v["enabled"], "configured": v["configured"],
                   "status": "ready" if v["enabled"] and v["configured"] else "disabled" if not v["enabled"] else "missing_environment"}
            for name, v in PROVIDERS.items()}
