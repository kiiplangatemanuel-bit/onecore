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

The backend normalizes PostgreSQL URLs to psycopg v3, enforces Supabase TLS, and disables psycopg prepared statements when using Supabase's transaction-mode pooler (port 6543). The backend database configuration also supports bounded connection-pool sizing and recycling. Do not guess a project hostname or pooler username.\n\n## Support file attachments\n\nSupport attachments use private S3-compatible object storage through the backend; the browser receives only short-lived presigned PUT/GET URLs. Configure these API-service secrets when enabling attachments:\n\n- `INTEGRATION_OBJECT_STORAGE_ENABLED=true`\n- `S3_ENDPOINT_URL` — exact S3-compatible endpoint from your storage provider (Supabase Storage S3 endpoint or approved S3 service)\n- `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY` — dedicated least-privilege bucket credentials\n- `S3_BUCKET` and `S3_REGION`\n\nThe API accepts PDF, PNG, JPEG, TXT and CSV files up to 10 MiB. Upload URLs expire after five minutes; download URLs expire after two minutes and force attachment download with an octet-stream response type. The bucket must remain private and must not allow anonymous reads. Configure bucket CORS to allow PUT from each exact deployed portal origin and the `Content-Type` request header. Do not put storage credentials in Vercel or browser environment variables. Uploads enter `pending_scan` quarantine and cannot be downloaded until a platform support administrator records an `available` or `rejected` review result. This is a manual release gate, not an antivirus scanner; connect an automated malware scanner and immutable scan evidence before treating file inspection as automated.

## Docker Compose

The API and CRM scheduler both receive the same database URL. Set `SUPABASE_DB_URL` in the project `.env` file or provide `ONECORE_DATABASE_URL` as the explicit Compose override. Compose uses the override first, then `SUPABASE_DB_URL`, and falls back to local SQLite only for development.

## Frontend security boundary

Set only `VITE_API_BASE_URL` in Vercel to the public HTTPS FastAPI origin. The browser uses OneCore's authenticated API and tenant context. Never add `SUPABASE_DB_URL`, a database password or a Supabase service-role key to frontend environment variables, source code or browser storage.

## Release verification

Use a disposable Supabase staging project to verify:
- Alembic upgrade to head and full downgrade/re-upgrade, including migrations 0054 (Support ticket/message RLS) and 0055 (private Support attachment metadata/RLS).
- Python compilation, full pytest and Vite production build.
- PostgreSQL row locking, uniqueness, transaction rollback, idempotency and concurrent goods-receipt/settlement operations.
- API/worker schema parity, backup/PITR and restore rehearsal.

Migration 0052 enables RLS for portal workflow records, migration 0053 adds MFA tables, and migrations 0054–0055 enable and force RLS for Support tickets/messages and Support attachment metadata. The API binds verified OneCore identity and validated guest ticket-token hashes to transaction-local PostgreSQL settings. The production API database role must be a dedicated least-privilege role with `NOBYPASSRLS`; Supabase `postgres`/service-role credentials and any `BYPASSRLS` role bypass RLS and must not be used as the runtime application role. Verify the actual connected role and policies in staging before production rollout.\n\nDeveloper API keys are stored only as SHA-256 digests, require an active organization membership on every key-authenticated request, and are revoked server-side. The `X-OneCore-API-Key` header is accepted by the developer API example endpoint; do not use API keys in browser applications. The sandbox/production field currently labels credentials and does not establish a separate sandbox database/data plane.\n\nSQLite CI remains useful for fast regression tests but does not prove live Supabase connectivity, PostgreSQL locking behavior, backup recovery or production provider acceptance.


def test_webhook_routes_are_registered():
    from app.main import app
    paths = set(app.openapi()["paths"])
    assert "/api/v1/developer/webhooks/activate" in paths
    assert "/api/v1/developer/webhooks" in paths
    assert "/api/v1/developer/webhooks/{workflow_record_id}/rotate-secret" in paths
    assert "/api/v1/developer/webhooks/{workflow_record_id}/deliveries" in paths


def test_webhook_migration_has_tenant_rls_and_idempotency():
    from pathlib import Path
    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0057_developer_webhooks.py"
    source = migration.read_text()
    assert 'revision = "0057_developer_webhooks"' in source
    assert 'down_revision = "0056_developer_api_keys"' in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "uq_developer_webhook_endpoint_event" in source


def test_developer_application_creation_automatically_enqueues_subscribed_webhook():
    from app.api.portal_workflows import PortalRecordCreate, create_portal_record

    engine = _db()
    with Session(engine) as db:
        org = Organization(name="Tenant", slug="tenant")
        db.add(org)
        db.flush()
        user = _developer(db, org)
        webhook_record = _webhook(db, org, user)
        endpoint = DeveloperWebhookEndpoint(
            workflow_record_id=webhook_record.id, organization_id=org.id,
            endpoint_url="https://hooks.example.com/onecore",
            events=["application.created"],
            secret_encrypted=webhooks._encrypt("whsec_test"), active=True,
        )
        db.add(endpoint)
        db.commit()
        created = create_portal_record(
            "developers", "application",
            PortalRecordCreate(
                organization_id=org.id, visibility="organization",
                payload={"name": "Payroll integration"},
            ), user, db,
        )
        delivery = db.query(DeveloperWebhookDelivery).filter_by(
            endpoint_id=endpoint.id, event_type="application.created"
        ).one()
        assert delivery.status == "pending"
        assert delivery.payload["data"]["record_id"] == created["id"]
        assert delivery.event_id == f"evt_application_{created['id']}_created"
    engine.dispose()


def test_webhook_test_event_is_endpoint_scoped_and_rate_limited():
    engine = _db()
    with Session(engine) as db:
        org = Organization(name="Tenant", slug="tenant")
        db.add(org)
        db.flush()
        user = _developer(db, org)
        record = _webhook(db, org, user)
        endpoint = DeveloperWebhookEndpoint(
            workflow_record_id=record.id, organization_id=org.id,
            endpoint_url="https://hooks.example.com/onecore",
            events=["organization.updated"],
            secret_encrypted=webhooks._encrypt("whsec_test"), active=True,
        )
        db.add(endpoint)
        db.commit()
        queued = webhooks.send_webhook_test(record.id, user, db)
        assert queued["queued_deliveries"] == 1
        delivery = db.query(DeveloperWebhookDelivery).one()
        assert delivery.payload["data"]["test"] is True
        with pytest.raises(HTTPException) as limited:
            webhooks.send_webhook_test(record.id, user, db)
        assert limited.value.status_code == 429
    engine.dispose()


def test_webhook_worker_rejects_out_of_range_batches():
    engine = _db()
    with Session(engine) as db:
        with pytest.raises(ValueError):
            webhooks.process_webhook_deliveries(db, 0)
        with pytest.raises(ValueError):
            webhooks.process_webhook_deliveries(db, 251)
    engine.dispose()
