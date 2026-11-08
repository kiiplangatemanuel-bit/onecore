# Security baseline

- Use HTTPS, managed secrets, secure password hashing, short-lived tokens and MFA/SSO before production.
- Keep Support uploads in private object storage; require an explicit clean ClamAV verdict before downloads, and fail closed on scanner errors.
- Enforce tenant and branch isolation at API, service and database access layers; add negative cross-tenant tests.
- Apply least privilege and separate customer, tenant admin, developer, partner, support and OneCore staff roles.
- Require mandatory MFA, privileged-session logging and approval for high-impact Superadmin actions.
- Verify payment/provider callback signatures; never trust browser redirects as proof of payment.
- Use idempotency keys for payment and asynchronous transaction processing.
- Encrypt sensitive data at rest and in transit; use private object storage and expiring signed links.
- Add CSRF/XSS/SQLi/IDOR protections, rate limits, abuse controls, malware scanning and secure upload validation.
- Maintain tamper-evident audit records, retention and authorized export/deletion workflows.
- Test backup integrity, restore, PITR, RTO/RPO and disaster recovery.
- Conduct independent security review and privacy impact assessment before handling real health/financial/identity data.
