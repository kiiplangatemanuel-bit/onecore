# Platform security and infrastructure baseline

## Implemented application controls

- Production settings validation rejects the development signing key, short JWT secrets,
  debug mode, SQLite, wildcard CORS/host allowlists and deployments without HTTPS.
- Bootstrap administrator creation is disabled unless both bootstrap credentials are
  explicitly supplied. There is no built-in production administrator password.
- Access-token lifetime is constrained to 5–60 minutes.
- CORS uses explicit methods and headers and does not enable credentialed browser cookies.
- Trusted-host validation is enabled when an explicit host allowlist is configured.
- Login requests have a bounded per-process IP rate limiter and return HTTP 429 with
  Retry-After; successful authentication clears that source's counter.
- TOTP seeds are encrypted at rest, recovery codes are single-use digests, and
  privileged platform roles are required to complete MFA before receiving an
  ordinary API session. Password and Supabase Auth flows share the policy.
- Privileged users without an accepted factor receive a ten-minute setup-only
  token accepted only by MFA status/enrollment/confirmation routes. It cannot
  access the normal API surface; enrollment increments the auth version and
  invalidates the setup token.
- Responses carry request IDs, clickjacking/MIME/referrer/permissions protections,
  a restrictive baseline CSP, HSTS on HTTPS, and no-store headers for API responses.
- /health is a liveness endpoint; /ready performs a database connectivity check and
  returns 503 without leaking connection details.
- Container runs as a non-root user and exposes a Docker health check.

## Required production deployment configuration

Set APP_ENV=production, DEBUG=false, SECRET_KEY to at least 32 random characters,
DATABASE_URL to managed PostgreSQL, CORS_ORIGINS to exact HTTPS origins,
TRUSTED_HOSTS to exact DNS names, FORCE_HTTPS=true, and configure secrets through a
secret manager rather than committing .env files. Set BOOTSTRAP_ADMIN_EMAIL and
BOOTSTRAP_ADMIN_PASSWORD together only for a controlled first boot; remove them
after the administrator account is created.

Terminate TLS at a trusted ingress/load balancer and configure it to enforce HTTPS,
forward only validated traffic, and apply a distributed/WAF login and API rate limit.
Do not trust arbitrary X-Forwarded-For headers. Configure managed database backups,
point-in-time recovery, encryption, private networking, monitoring, alerting, log
retention, and a tested restore/rollback procedure. Keep API workers and the database
on private networks where possible.

## Explicit remaining release gates

The login limiter in this application is process-local and resets on restart; it is
not a substitute for distributed edge throttling. Organization-level/custom-role
MFA policy, passkeys/WebAuthn, OIDC/SSO federation, privileged step-up/dual approval,
durable per-device session inventory and per-session revocation, centralized audit
tamper-evidence and secret-rotation automation remain open. Email verification and
password recovery workflows exist but require SMTP credentials, sender-domain
authentication, delivery monitoring and retry-worker operations. Complete object
storage malware scanning/retention, automated backup/PITR and restore-drill evidence,
metrics/tracing/alerts, penetration testing, load testing, privacy impact assessment
and production UAT also require implementation or external operational configuration.
The CSP allows inline scripts for existing server-rendered screens; remove inline
scripts and tighten script-src before enforcing a nonce/hash-only policy.

This baseline is not a security certification and does not prove a deployed
environment is secure. Reassess these controls against the actual ingress, database,
identity provider and cloud account before production use.
