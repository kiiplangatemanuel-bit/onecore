# Supabase PostgreSQL deployment for OneCore

Supabase is the managed PostgreSQL database for OneCore. FastAPI uses SQLAlchemy and Alembic against Supabase PostgreSQL. The browser frontend must never connect directly to the database or receive a database password, connection string or service-role key.

## Backend configuration

1. In Supabase **Project Settings → Database → Connection string**, copy the URI for the chosen connection mode.
2. Prefer the Session pooler for a long-running Render API service when direct IPv6 connectivity is unavailable. Use the exact hostname, port and username Supabase provides. Transaction pooler (normally port 6543) is also supported.
3. Set the backend-only Render secret `DATABASE_URL` to the copied URI and include `sslmode=require`.
4. Set `APP_ENV=production`, `DEBUG=false`, a unique `SECRET_KEY` of at least 32 random characters, explicit HTTPS `CORS_ORIGINS`, explicit `TRUSTED_HOSTS` and `FORCE_HTTPS=true`.
5. Run Alembic migrations in a release step before routing production traffic. Do not use `Base.metadata.create_all` as a production migration strategy.
6. Never put the database URI in Vite variables, frontend source, GitHub, logs or screenshots.

Example format only; replace every placeholder with the exact values shown by Supabase:

```text
DATABASE_URL=postgresql+psycopg://postgres.<project-ref>:<database-password>@<pooler-host>:<pooler-port>/postgres?sslmode=require
```

The application normalizes Supabase's `postgres://` and `postgresql://` URI schemes to the installed psycopg v3 driver. The transaction pooler path disables psycopg auto-prepared statements and uses a non-persistent client pool. Do not guess project-specific hosts, ports or usernames.

## Frontend boundary

Vite frontend calls only the authenticated FastAPI API. Set `VITE_API_BASE_URL` to the public HTTPS Render API origin. Keep OneCore JWT authentication on the API; do not expose Supabase service-role or database credentials to the browser.

## Release verification

Use a disposable Supabase staging project to verify Alembic upgrade, downgrade/re-upgrade, Python compilation and pytest. Add PostgreSQL-specific checks for row locking, unique constraints, transaction rollback, idempotency and concurrent GRN/settlement operations. Verify API and workers use the same Supabase project/schema revision, and rehearse backup/PITR restore. SQLite tests do not prove Supabase/PostgreSQL concurrency or production connectivity.
