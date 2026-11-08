# Supabase PostgreSQL (OneCore system of record)

OneCore's backend is already wired to Supabase-managed PostgreSQL through SQLAlchemy/psycopg and Alembic. The `SUPABASE_DB_URL` setting takes precedence over `DATABASE_URL`. Existing procurement, accounting, inventory, HR and other domain models therefore share the same Supabase database and migration chain; no second browser-side database client is required.

## Configure Render

1. Open Supabase **Project Settings → Database → Connection string** and copy the URI for your project and selected connection mode.
2. In Render, add `SUPABASE_DB_URL` as a secret environment variable on the API service. Use the exact host, port, username and password Supabase provides, and include `sslmode=require`.
3. Set `APP_ENV=production`, `DEBUG=false`, a unique `SECRET_KEY`, explicit HTTPS `CORS_ORIGINS`, explicit `TRUSTED_HOSTS`, and `FORCE_HTTPS=true`.
4. Configure any worker/scheduler services with the same `SUPABASE_DB_URL`. They must use the same Supabase project and schema revision as the API.
5. Run Alembic migrations in the controlled release step before routing traffic. Do not run destructive downgrade operations against production.

Example format only — copy actual values from the Supabase dashboard and never commit the completed URI:

```text
SUPABASE_DB_URL=postgresql://postgres.<project-ref>:<database-password>@<supabase-host>:5432/postgres?sslmode=require
```

The backend normalizes PostgreSQL URLs to psycopg v3, enforces Supabase TLS, and disables psycopg prepared statements when using Supabase's transaction-mode pooler (port 6543). The backend database configuration also supports bounded connection-pool sizing and recycling. Do not guess a project hostname or pooler username.

## Docker Compose

The API and CRM scheduler both receive the same database URL. Set `SUPABASE_DB_URL` in the project `.env` file or provide `ONECORE_DATABASE_URL` as the explicit Compose override. Compose uses the override first, then `SUPABASE_DB_URL`, and falls back to local SQLite only for development.

## Supabase Auth and frontend security boundary

Set backend `SUPABASE_URL` to the project URL. The API validates Supabase Auth access tokens using the project's JWKS endpoint for asymmetric signing, or `SUPABASE_JWT_SECRET` for legacy HS256 signing. The JWT secret is server-only. Verified identities are linked to an existing OneCore account by exact email or provisioned as a new OneCore identity with no organization membership. Organization registration after Supabase email verification is completed through the authenticated onboarding endpoint.

Set `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` (or publishable key) in each Vercel app to use Supabase Auth sign-in/sign-up. These are public browser settings and must be paired with strict Supabase Auth settings. The frontend must use the OneCore API for business data. Never add `SUPABASE_DB_URL`, a database password, `SUPABASE_JWT_SECRET` or a Supabase service-role key to frontend variables, source code or browser storage.

## Release verification

Use a disposable Supabase staging project to verify:
- Alembic upgrade to head and full downgrade/re-upgrade.
- Python compilation, full pytest and Vite production build.
- PostgreSQL row locking, uniqueness, transaction rollback, idempotency and concurrent goods-receipt/settlement operations.
- API/worker schema parity, backup/PITR and restore rehearsal.

SQLite CI remains useful for fast regression tests but does not prove live Supabase connectivity, PostgreSQL locking behavior, backup recovery or production provider acceptance.
