# External integration setup

All provider integrations are disabled by default. `.env.example` lists supported configuration keys. Environment variables are not a substitute for provider onboarding, legal authority, certification or UAT.

| Provider | Environment prefix | Notes |
|---|---|---|
| M-Pesa | `MPESA_` + `INTEGRATION_MPESA_ENABLED` | STK Push/C2B/B2C as contracted; verify callbacks, idempotency and settlement reconciliation. |
| KRA eTIMS | `ETIMS_` + `INTEGRATION_ETIMS_ENABLED` | Use current authorized OSCU/VSCU method and approved credentials. |
| SHA/DHA AfyaLink | `SHA_` + `INTEGRATION_SHA_ENABLED` | Facility/provider onboarding and approved scopes required; health data is restricted. |
| Banks | `BANK_` + `INTEGRATION_BANK_ENABLED` | Bank-approved API/file exchange and reconciliation. |
| Email/SMS/WhatsApp | respective prefixes | Consent, opt-out, templates, provider limits and delivery callbacks. |
| AI | `AI_` + `INTEGRATION_AI_ENABLED` | Tenant-aware routing, cost caps, data policies and model/version logs. |
| Object storage | `S3_` + `INTEGRATION_OBJECT_STORAGE_ENABLED` | Private buckets by default; signed URLs; never expose tenant files on public CDN. |

Implement a class conforming to `IntegrationAdapter` for each provider. Keep request signing, token refresh, provider payload mapping, callback verification, retries, dead-letter handling and reconciliation inside the adapter/service boundary. Do not return secret values from API endpoints.

## Support attachment malware scanning

Support attachments are uploaded to a private object-storage bucket using short-lived presigned PUT URLs. Upload completion verifies the stored size and content type, then keeps the object quarantined until scanning returns an explicit clean verdict. Configure `SUPPORT_ATTACHMENT_SCANNING_ENABLED=true`, `CLAMAV_HOST`, `CLAMAV_PORT` (default `3310`) and `CLAMAV_TIMEOUT_SECONDS` (default `30`) to use a reachable ClamAV `clamd` service. The API streams the object to ClamAV using `INSTREAM`; infected files are marked rejected and scanner errors/timeouts leave files quarantined. Only clean files can receive short-lived download URLs. Keep the ClamAV service on a private network, do not publish port 3310 publicly, keep signatures updated, and monitor daemon health. Production startup validation refuses to enable Support object storage without scanning enabled. Manual platform-admin review remains a separate fallback only when automated scanning is not configured in non-production environments.
