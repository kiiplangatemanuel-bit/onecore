# CRM campaign delivery and communications

Campaigns support consent-gated preparation and manager-triggered batch dispatch.
Dispatch rechecks the latest channel-specific marketing consent for every recipient,
records attempts and provider responses, and uses a stable provider idempotency key.
A maximum of five attempts is recorded per recipient. Provider acceptance is shown
as sent; only an authenticated provider callback can mark a message delivered.
Failed, delivered, and suppressed recipient counts and attempt totals are reportable.

Email uses SMTP with STARTTLS. SMS and WhatsApp use configured HTTP endpoints with
the normalized JSON contract: to, message, subject, sender, idempotency_key and
unsubscribe_url. Providers return message_id or id and must honor Idempotency-Key
for safe retries. Provider callback requests POST provider_message_id and status
(delivered or failed) with X-CRM-Delivery-Secret.

Configure INTEGRATION_EMAIL_ENABLED, EMAIL_HOST, EMAIL_PORT, EMAIL_USERNAME,
EMAIL_PASSWORD, EMAIL_FROM; INTEGRATION_SMS_ENABLED, SMS_BASE_URL, SMS_API_KEY,
SMS_SENDER_ID; INTEGRATION_WHATSAPP_ENABLED, WHATSAPP_BASE_URL, WHATSAPP_TOKEN,
WHATSAPP_PHONE_NUMBER_ID; CRM_PUBLIC_BASE_URL (HTTPS) and
CRM_DELIVERY_CALLBACK_SECRET (high entropy).

One-click unsubscribe tokens are random, single-purpose bearer links stored only
as SHA-256 digests. Unsubscribe appends a channel-specific revoked consent decision
and suppresses that recipient. Dispatch is a bounded manager-triggered API batch,
not an automatic background scheduler. Provider credentials, live provider UAT,
SPF/DKIM/DMARC, WhatsApp template approval and local legal/privacy review are
deployment requirements. Providers without idempotency support cannot guarantee
exactly-once delivery after ambiguous network failures.
