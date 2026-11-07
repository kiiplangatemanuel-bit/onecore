# CRM campaign delivery and communications

Campaigns support consent-gated preparation and manager-triggered batch dispatch.
Dispatch rechecks the latest channel-specific marketing consent immediately before
each provider call, records durable attempts and provider responses, and uses a
stable provider idempotency key across retries. A maximum of five attempts is
recorded per recipient. Provider acceptance is shown as sent; only an authenticated
provider callback can mark a message delivered. Failed, delivered, suppressed and
exhausted recipient counts and attempt totals are reportable.

Dispatch claims recipients in bounded batches. Claims have a ten-minute lease and
stale sending claims are recoverable after a process crash. Network timeouts are
shorter than the lease. Provider idempotency is still required to prevent duplicate
delivery when a provider accepted a request but the connection failed before OneCore
received the response; providers without idempotency support cannot guarantee
exactly-once delivery after ambiguous network failures.

Marketing dispatch is blocked unless CRM_PUBLIC_BASE_URL is a public HTTPS URL.
Unsubscribe GET requests render a confirmation page without changing consent; only
an explicit POST (including RFC 8058 one-click POST) revokes consent. This prevents
link scanners and message-preview bots from unsubscribing a customer merely by
fetching a link. Email includes both
List-Unsubscribe and RFC 8058 List-Unsubscribe-Post headers. One-click unsubscribe
tokens are random, single-purpose bearer links stored only as SHA-256 digests.
Unsubscribe appends a channel-specific revoked consent decision and suppresses that
recipient.

Email uses SMTP with STARTTLS. SMTP acceptance is not a delivery receipt; the
recipient remains in the accepted/sent state unless the configured mail transport
or event bridge reports a delivery event to OneCore. SMS and WhatsApp use configured
HTTP endpoints with the normalized JSON contract: to, message, subject, sender,
idempotency_key and unsubscribe_url. Providers return message_id or id and must
honor the Idempotency-Key header. Provider callback requests POST
provider_message_id and status (delivered or failed) with
X-CRM-Delivery-Secret.

Configure INTEGRATION_EMAIL_ENABLED, EMAIL_HOST, EMAIL_PORT, EMAIL_USERNAME,
EMAIL_PASSWORD, EMAIL_FROM; INTEGRATION_SMS_ENABLED, SMS_BASE_URL, SMS_API_KEY,
SMS_SENDER_ID; INTEGRATION_WHATSAPP_ENABLED, WHATSAPP_BASE_URL, WHATSAPP_TOKEN,
WHATSAPP_PHONE_NUMBER_ID; CRM_PUBLIC_BASE_URL (public HTTPS) and
CRM_DELIVERY_CALLBACK_SECRET (high entropy).

Dispatch is a bounded manager-triggered API batch, not an automatic background
scheduler. Provider credentials, live provider UAT, SPF/DKIM/DMARC, WhatsApp
template approval and local legal/privacy review are deployment requirements.
