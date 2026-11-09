# Supabase PostgreSQL (OneCore system of record)

OneCore uses Supabase-managed PostgreSQL through SQLAlchemy/psycopg and Alembic. The application ORM and Alembic migrations support separate connection URLs: `DATABASE_URL` is the ORM connection and `ALEMBIC_DATABASE_URL` is the migration connection. `SUPABASE_DB_URL` remains a compatibility fallback for older deployments.

## Configure Render

1. Open Supabase **Project Settings → Database → Connection string** and copy the URI for your project and selected connection mode.
2. In Render, set `DATABASE_URL` to the Supabase Session Pooler URI for the application ORM and `ALEMBIC_DATABASE_URL` to the migration URI. They may initially contain the same connection string; separate credentials can be introduced after their database privileges are designed and tested.
3. Keep `SUPABASE_DB_URL` only as a compatibility fallback. Explicit `DATABASE_URL` wins for the ORM; explicit `ALEMBIC_DATABASE_URL` wins for migrations. Set `APP_ENV=production`, `DEBUG=false`, a unique `SECRET_KEY`, explicit HTTPS `CORS_ORIGINS`, explicit `TRUSTED_HOSTS`, and `FORCE_HTTPS=true`.
4. Configure any worker/scheduler services with the same `SUPABASE_DB_URL`. They must use the same Supabase project and schema revision as the API.
5. Run Alembic migrations in the controlled release step before routing traffic. Do not run destructive downgrade operations against production.

Example format only — copy actual values from the Supabase dashboard and never commit the completed URI:

```text
DATABASE_URL=postgresql://postgres.<project-ref>:<database-password>@<supabase-session-pooler-host>:5432/postgres?sslmode=require
ALEMBIC_DATABASE_URL=postgresql://postgres.<project-ref>:<database-password>@<supabase-session-pooler-host>:5432/postgres?sslmode=require
SUPABASE_DB_URL=postgresql://postgres.<project-ref>:<database-password>@<supabase-host>:5432/postgres?sslmode=require
```

The ORM selects `DATABASE_URL` first, then `SUPABASE_DB_URL` for compatibility (and local SQLite remains available in development). Alembic selects `ALEMBIC_DATABASE_URL` first, then `SUPABASE_DB_URL`, then the effective ORM URL. Production validates both effective URLs as Supabase PostgreSQL and rejects bare `postgres` usernames for shared-pooler connections. Both connections normalize PostgreSQL URLs to psycopg v3 and enforce Supabase TLS. Transaction-mode pooler connections on port 6543 disable psycopg prepared statements. The backend database configuration also supports bounded connection-pool sizing and recycling. Do not guess a project hostname or pooler username.

## Support file attachments

Support attachments use private S3-compatible object storage through the backend; the browser receives only short-lived presigned PUT/GET URLs. Configure these API-service secrets when enabling attachments:

- `INTEGRATION_OBJECT_STORAGE_ENABLED=true`
- `S3_ENDPOINT_URL` — exact S3-compatible endpoint from your storage provider (Supabase Storage S3 endpoint or approved S3 service)
- `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY` — dedicated least-privilege bucket credentials
- `S3_BUCKET` and `S3_REGION`

The API accepts PDF, PNG, JPEG, TXT and CSV files up to 10 MiB. Upload URLs expire after five minutes; download URLs expire after two minutes and force attachment download with an octet-stream response type. The bucket must remain private and must not allow anonymous reads. Configure bucket CORS to allow PUT from each exact deployed portal origin and the `Content-Type` request header. Do not put storage credentials in Vercel or browser environment variables. Uploads remain quarantined and cannot be downloaded until an explicit clean automated scan verdict. Manual security review can reject a file but cannot release it. Automated scanning uses ClamAV daemon INSTREAM over a private TCP connection. Configure `SUPPORT_ATTACHMENT_SCANNING_ENABLED=true`, `CLAMAV_HOST`, optional `CLAMAV_PORT` (default 3310), and `CLAMAV_TIMEOUT_SECONDS` (default 30) on the API service; restrict the scanner port to the API network and never expose it publicly. A clean verdict marks the attachment available; a malware signature marks it rejected. Scanner errors, timeouts, malformed responses and missing configuration fail closed and leave the attachment quarantined. Migration 0058 records engine, verdict, signature and scan timestamp for auditability. The authenticated platform-admin scan endpoint can retry quarantined files and records the SHA-256 digest, byte count, scanner verdict and actor in the audit stream. If automated scanning is disabled in development, uploads stay `pending_scan`; production refuses to enable Support object storage without automated scanning.

## Docker Compose

The API and CRM scheduler both receive the same database URL. Set `DATABASE_URL` and `ALEMBIC_DATABASE_URL` in the project `.env` file, or retain `SUPABASE_DB_URL` as the compatibility fallback. Local SQLite remains development-only.

## Frontend security boundary

Set only `VITE_API_BASE_URL` in Vercel to the public HTTPS FastAPI origin. The browser uses OneCore's authenticated API and tenant context. Never add `DATABASE_URL`, `ALEMBIC_DATABASE_URL`, `SUPABASE_DB_URL`, a database password or a Supabase service-role key to frontend environment variables, source code or browser storage.

## Release verification

Use a disposable Supabase staging project to verify:
- Alembic upgrade to head and full downgrade/re-upgrade, including migrations 0054 (Support ticket/message RLS) and 0055 (private Support attachment metadata/RLS).
- Python compilation, full pytest and Vite production build.
- PostgreSQL row locking, uniqueness, transaction rollback, idempotency and concurrent goods-receipt/settlement operations.
- API/worker schema parity, backup/PITR and restore rehearsal.

Migration 0052 enables RLS for portal workflow records, migration 0053 adds MFA tables, migrations 0054–0055 enable and force RLS for Support tickets/messages and Support attachment metadata, and migration 0059 enables and forces tenant RLS across organization-owned domain tables (including inventory, accounting, CRM, procurement, POS, school and healthcare records). Migration 0059 adds dedicated membership policies (users see their own memberships; tenant administrators can manage memberships within their tenant but cannot grant the `org_admin` role; platform administrators retain controlled access) and append-only audit-event policies for authenticated tenant activity and validated guest Support events. Fixed-search-path SECURITY DEFINER helpers avoid recursive membership-policy evaluation. The API binds verified OneCore identity, verified tenant scope for background CRM scheduling, provider callback token hashes (M-Pesa and supplier settlements), CRM delivery callback provider-message IDs (after shared-secret verification), CRM unsubscribe token hashes, and validated guest ticket-token hashes to transaction-local PostgreSQL settings. Integration contexts are set only after server-side credential/token validation and are cleared automatically at transaction boundaries; the CRM scheduler iterates one organization at a time. The production API database role must be a dedicated least-privilege role with `NOBYPASSRLS`; Supabase `postgres`/service-role credentials and any `BYPASSRLS` role bypass RLS and must not be used as the runtime application role. The `/ready` endpoint verifies the runtime role and a critical set of portal, Support, developer and core business RLS tables before reporting production readiness. Verify the complete migration and policy set in staging before production rollout.

Developer API keys are stored only as SHA-256 digests, require an active organization membership on every key-authenticated request, and are revoked server-side. The `X-OneCore-API-Key` header is accepted by the developer API example endpoint; do not use API keys in browser applications. Sandbox API keys are isolated from production tenant records: the organization example endpoint returns synthetic OneCore sandbox fixture data for sandbox keys, while production keys return only their authorized organization. Issuing a production API key requires an active organization administrator; developers can issue sandbox keys and manage their own credentials. This is an API-level fixture environment, not a separate PostgreSQL database or production-equivalent data plane.

In production, `/ready` also verifies that the connected API database role is neither a superuser nor `BYPASSRLS`, and that portal workflow, Support ticket/message/attachment, developer API-key/usage and webhook endpoint/delivery tables exist with RLS enabled, forced and at least one policy. A failed check returns HTTP 503 so the deployment platform does not route traffic to an unsafe or incompletely migrated API. Provision a dedicated `NOBYPASSRLS` API login and apply migrations before expecting readiness to pass. This guard is a deployment safety check, not a substitute for reviewing each policy's authorization semantics or testing cross-tenant access.

SQLite CI remains useful for fast regression tests but does not prove live Supabase connectivity, PostgreSQL locking behavior, backup recovery or production provider acceptance.


## Supabase Auth identity provider

Migration 0057 adds a unique `users.supabase_auth_user_id` mapping. The optional shared-login flow requires backend `SUPABASE_URL` and `SUPABASE_ANON_KEY`, plus matching central-frontend `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`. The API verifies the supplied access token by calling the configured Supabase Auth `/auth/v1/user` endpoint over HTTPS, requires a confirmed email, rejects anonymous sessions, and issues a short-lived OneCore JWT after linking/provisioning the OneCore identity. The anon/publishable key is not a service-role credential. Never expose the Supabase service-role key in a frontend variable.

## Developer webhook delivery (migration 0057)

Migration 0057 adds private webhook endpoint signing material and a tenant-scoped durable delivery outbox with endpoint/event idempotency. Signing secrets are encrypted at rest using a key derived from the API `SECRET_KEY`; keep that key stable across restarts and restores. The separate worker uses a dedicated PostgreSQL role named `onecore_webhook_worker` (NOBYPASSRLS) with narrowly scoped SELECT/UPDATE grants and RLS policies; it cannot elevate itself by setting a session variable. Configure `WEBHOOK_WORKER_DATABASE_URL` with that role's connection string. Never reuse the public API or Supabase service-role credentials for the worker. Schedule `python -m app.workers.webhook_delivery --batch-size 25` from a worker/cron service. Do not expose the worker as a public endpoint.

Webhook delivery uses HTTPS, public DNS address validation, no redirects, no inherited proxy configuration, bounded timeouts, HMAC-SHA256 signatures, and exponential retries (maximum eight attempts). Network egress restrictions and DNS pinning remain deployment responsibilities; configure outbound egress to approved destinations where possible. The worker role must be provisioned by the database administrator after migration and granted SELECT on `developer_webhook_endpoints` and `developer_webhook_deliveries`, plus SELECT on `memberships` for the worker RLS policy, and UPDATE on `developer_webhook_deliveries`; the RLS policies still apply.


For PostgreSQL deployments, provision the worker login after applying migration 0057. Use a unique password and store the connection URI only in the worker's secret environment:

```sql
CREATE ROLE onecore_webhook_worker LOGIN PASSWORD '<generated-secret>' NOBYPASSRLS;
GRANT CONNECT ON DATABASE postgres TO onecore_webhook_worker;
GRANT USAGE ON SCHEMA public TO onecore_webhook_worker;
GRANT SELECT ON TABLE public.memberships, public.developer_webhook_endpoints,
    public.developer_webhook_deliveries TO onecore_webhook_worker;
GRANT UPDATE ON TABLE public.developer_webhook_deliveries TO onecore_webhook_worker;
```

Set `WEBHOOK_WORKER_DATABASE_URL` to a connection URI using this login. Do not grant table ownership, `BYPASSRLS`, schema creation, or broad write privileges. The API runtime role remains separate and uses the normal OneCore user-identity RLS context.

## Status alert delivery outbox (migration 0060)

Public Status incidents enqueue idempotent email deliveries for matching active Status alert subscriptions in the same transaction as the incident publication/update. The worker retries transient delivery failures with bounded exponential backoff (maximum eight attempts). Run `python -m app.workers.status_alert_delivery` as a private worker process; do not expose it through the API.

Provision a separate `NOBYPASSRLS` role and set `STATUS_ALERT_WORKER_DATABASE_URL` only in the worker's secret environment:

```sql
CREATE ROLE onecore_status_alert_worker LOGIN PASSWORD '<generated-secret>' NOBYPASSRLS;
GRANT CONNECT ON DATABASE postgres TO onecore_status_alert_worker;
GRANT USAGE ON SCHEMA public TO onecore_status_alert_worker;
GRANT SELECT, UPDATE ON TABLE public.status_alert_deliveries TO onecore_status_alert_worker;
GRANT SELECT, INSERT ON TABLE public.status_alert_deliveries TO onecore_api;
GRANT USAGE, SELECT ON SEQUENCE public.status_alert_deliveries_id_seq TO onecore_api;
```

The worker verifies its connected PostgreSQL role at startup. The outbox RLS policy permits subscribers to read only their own deliveries; only the dedicated worker role can update delivery state. Configure SMTP using the existing email integration settings. Never reuse the API or Supabase service-role database credentials for this worker.
