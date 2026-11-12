# Shared API rate limiting

## Scope

The API now stores login and selected public-write quotas in PostgreSQL so all
application workers using the same database share a counter. This replaces the
previous per-process limiter in the production middleware. Login and public-write
quotas have separate scopes and configurable fixed windows.

The bucket key is HMAC-SHA256 over the scope and the trusted ASGI client address,
using the application secret key. Raw IP addresses, email addresses and passwords
are not written to the rate-limit table. The middleware does not trust arbitrary
X-Forwarded-For headers; configure the trusted ingress to provide the actual
client address through the ASGI server/proxy configuration.

## Database and security

Migration `0069_platform_distributed_rate_limits` creates
`platform_rate_limit_buckets`, enables and forces PostgreSQL RLS, and grants the
table to the pre-provisioned `onecore_api` role when that role exists. Every
rate-limit transaction sets the transaction-local
`app.platform_rate_limit_service=enabled` context. Without that context, the
forced RLS policy returns no rows and rejects writes. Expired buckets are pruned
opportunistically by API workers; the table contains only HMAC keys, scope names
and counters.

Production requires the normal OneCore runtime role to be a non-superuser
`NOBYPASSRLS` role with the reviewed table grants. If `onecore_api` did not
exist when migration 0069 ran, grant SELECT, INSERT, UPDATE and DELETE on this
table to that role after review. Do not grant these permissions to tenant-facing
roles or browser clients.

## Current middleware policy

- Login and Supabase session exchange use the configured login limit (default
  five attempts per 60 seconds per trusted client address).
- Registration, email verification, portal-code exchange, password-reset,
  MFA-challenge and public Support ticket writes use five requests per five
  minutes per trusted client address.
- Store/database errors fail closed with HTTP 503 rather than silently falling
  back to a process-local quota.
- A successful login does not erase the shared IP bucket; one valid account on a
  shared network must not reset the quota for other users.

## Verification and remaining controls

CI verifies two independent limiter instances share one SQLite test store, fixed
window expiry, scope isolation, HMAC non-disclosure, PostgreSQL forced-RLS service
context, and migration upgrade/downgrade/re-upgrade. The CI PostgreSQL role is
disposable and does not prove production Supabase grants or ingress behavior.

This does not replace edge/WAF controls, bot detection, account-level progressive
lockout, credential-stuffing detection, device reputation, or distributed
monitoring/alerting. Those remain separate release requirements. No production
WAF or production database configuration is claimed.
