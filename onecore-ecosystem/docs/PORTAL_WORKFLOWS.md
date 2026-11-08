# OneCore real registration and support workflows

This release adds two database-backed workflows to the shared OneCore API.

## Organization registration and email verification

1. The public frontend submits organization details and the first administrator's account to `POST /api/v1/auth/register-organization`.
2. The API validates the request, enforces unique account email and organization slug, creates an inactive user, organization and `org_admin` membership in the same database transaction, and creates a single-use email-verification token hash.
3. The API sends the verification URL using the configured SMTP service. It does not return the raw verification token to the browser.
4. The user opens the verification URL. The frontend posts its token to `POST /api/v1/auth/verify-email`.
5. The API validates the token hash and 24-hour expiry, consumes the token once, activates the account and records an audit event. The user can then sign in.
6. The first user receives organization-admin membership only. The registration path always assigns `platform_role=customer`; it cannot create a platform superadmin.

Required backend environment:
- `INTEGRATION_EMAIL_ENABLED=true`
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_FROM`
- `EMAIL_USERNAME` and `EMAIL_PASSWORD` when required by the SMTP provider
- `EMAIL_USE_STARTTLS=true` for providers requiring STARTTLS
- `PUBLIC_SITE_URL` set to the public frontend origin that serves `/verify-email`

If the mail provider is not configured, registration fails with HTTP 503 before committing user and organization records. Configure the SMTP provider and test delivery in staging before enabling the registration CTA in production.

## Support tickets

Guest support:
- `POST /api/v1/support/public/tickets` creates a ticket and first message.
- The API returns a ticket number and a high-entropy one-time-displayed guest access token. Only the SHA-256 token hash is stored.
- `GET /api/v1/support/public/tickets/{ticket_number}` and `POST /api/v1/support/public/tickets/{ticket_number}/messages` require the `X-Support-Access-Token` header.
- A guest cannot access another ticket by guessing its ticket number; the token is checked using constant-time comparison.

Authenticated support:
- `POST /api/v1/support/tickets`, `GET /api/v1/support/tickets`, `GET /api/v1/support/tickets/{ticket_number}` and `POST /api/v1/support/tickets/{ticket_number}/messages` use the normal OneCore bearer token.
- Organization ID is accepted only when the signed-in user has an active membership in that organization.
- Users can view tickets they created; organization administrators can view tickets belonging to their organization.
- Resolved and closed tickets cannot receive customer replies.

Platform support administration:
- `GET /api/v1/support/admin/tickets`, `POST /api/v1/support/admin/tickets/{ticket_number}/messages` and `PATCH /api/v1/support/admin/tickets/{ticket_number}` require the backend's `require_platform_admin` dependency.
- Assignment is limited to active platform administrators. Organization administrator status does not grant platform support privileges.
- Ticket creation, replies and administrative changes create audit events.

## Database and deployment

Apply the Alembic chain through revision `0049_verified_org_registration` before deploying the updated API. This includes:
- `0048_support_ticketing`: `support_tickets` and `support_messages`.
- `0049_verified_org_registration`: user phone and `email_verifications`.

All records use the configured OneCore SQLAlchemy database connection. In production, configure `SUPABASE_DB_URL` to the Supabase-managed PostgreSQL connection and run `alembic upgrade head` as a controlled release step. Do not expose database credentials or service-role keys to the browser.

The independent Support frontend requires `VITE_API_BASE_URL` to point to the shared API. Add the Support origin to the backend's explicit `CORS_ORIGINS`; the API allows the `X-Support-Access-Token` header for guest ticket access. The public registration frontend must use the same API origin.

The API process-local public-write limiter permits five organization registrations or guest ticket creations per IP per five minutes. This is a basic per-worker safety net; production ingress/WAF rate limits should also be enabled because in-memory limits are not shared across multiple API workers.

## Verified scope and known boundaries

These are implemented database-backed workflows, not static cards. Email delivery requires the SMTP environment above and a working provider. Live Supabase operation requires a configured Supabase project and applied migrations. The portal packages still use the shared API bearer-token model; cross-subdomain SSO, support attachments, email notifications on ticket replies, SLA automation and a granular support-agent role remain separate work.
