# Identity email delivery

## Delivery model

Account verification and password-reset requests create a durable outbox row in the
same database transaction as the corresponding one-time token and audit event. The
API does not perform SMTP network I/O. The outbox contains only the account ID,
purpose, token-digest-derived idempotency key, expiry, delivery state and an encrypted
payload. Recipient address, subject, message body and the one-time URL are encrypted
together with Fernet; plaintext tokens are not stored in the outbox or token tables.

The outbox is account-owned and protected by PostgreSQL forced row-level security.
The API may select/insert only rows for the transaction-local `app.user_id`. It
may cancel only its own `pending`/`sending` rows using column-limited updates to
`status`, `last_error` and `updated_at`; the RLS check permits only the `cancelled`
state. It cannot mark a message delivered, change retry scheduling or delete rows.
The dedicated
`onecore_identity_email_worker` role can select and update the queue, but it is
not a superuser, table owner or RLS bypass role.

The worker uses row locks with `SKIP LOCKED`, an eight-attempt ceiling, bounded
exponential retry delay, a ten-minute stale-send recovery window and an expiry
check before SMTP. Superseded or expired pending password-reset deliveries are
cancelled. SMTP delivery is at-least-once: a process crash after the SMTP server
accepts a message but before the database records success can result in a duplicate.
The stable `X-OneCore-Delivery-ID` header helps operators correlate duplicates.

## Required configuration

Generate a dedicated Fernet key:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Store it as `IDENTITY_EMAIL_ENCRYPTION_KEY` in the secret manager. Do not commit it,
reuse the MFA/healthcare keys, print it in logs, or rotate it without a planned
re-encryption/drain procedure. Losing the key makes queued messages undecryptable.

Configure the existing SMTP settings:

- `INTEGRATION_EMAIL_ENABLED=true`
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_FROM`
- `EMAIL_USERNAME` and `EMAIL_PASSWORD` when the provider requires authentication
- `EMAIL_USE_STARTTLS=true`
- `PUBLIC_SITE_URL` to the canonical public HTTPS site

The API refuses registration queueing if encryption or delivery configuration is
missing. Password-reset requests retain a non-enumerating response and do not create
a token when queue encryption/configuration is unavailable.

## Worker database role

Provision the role before applying migration `0065_identity_email_outbox`, so the
migration can grant the narrow table permissions:

    CREATE ROLE onecore_identity_email_worker
      LOGIN PASSWORD '<managed-secret>'
      NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    GRANT CONNECT ON DATABASE <database_name> TO onecore_identity_email_worker;
    GRANT USAGE ON SCHEMA public TO onecore_identity_email_worker;

The migration grants only SELECT and UPDATE on `identity_email_deliveries`.
Configure the worker service with:

- `IDENTITY_EMAIL_WORKER_DATABASE_URL` using that dedicated role
- `ONECORE_DATABASE_RUNTIME_ROLE=onecore_identity_email_worker`
- `APP_ENV=production`
- The same `IDENTITY_EMAIL_ENCRYPTION_KEY` and SMTP settings as the API

The API runtime role (`onecore_api`) receives SELECT, INSERT and column-limited
cancellation updates only. If the role was not present when migration 0065 ran,
apply the reviewed SELECT/INSERT/sequence and column-level cancellation grants
manually; do not grant general UPDATE or DELETE to the API role.

Start the optional Docker Compose worker profile:

    docker compose --profile communications up -d identity-email-worker

The worker writes a local heartbeat at
`/tmp/identity-email-worker-heartbeat`; Compose checks that heartbeat. Queue state
can be inspected by an authorized operator with:

    SELECT status, purpose, count(*), min(next_attempt_at) AS oldest_due
    FROM identity_email_deliveries
    GROUP BY status, purpose
    ORDER BY status, purpose;

Rows at `failed` require operator review. Do not manually edit ciphertext or mark
a row delivered without provider evidence. Keep retention and key rotation aligned
with account-token expiry and privacy requirements.

## Verification and limitations

CI exercises encrypted payload round-tripping, plaintext exclusion, missing/invalid
key fail-closed behavior, worker success/retry/expiry handling, and PostgreSQL RLS
under separate API and worker roles. These are disposable CI database tests only.
Production SMTP delivery, sender-domain SPF/DKIM/DMARC, provider deliverability,
bounce/complaint processing, queue dashboards, automated dead-letter replay and
production role provisioning still require deployment configuration and operational
acceptance. No live email provider or production delivery is claimed.
