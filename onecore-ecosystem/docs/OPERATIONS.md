# Operations runbook

## Deploy

1. Build and scan the application container and frontend artifacts.
2. Supply production configuration through the hosting platform's secret manager. Do not commit .env files or credentials. Set APP_ENV=production, the signing key, PostgreSQL DATABASE_URL, exact HTTPS CORS/host allowlists, SMTP settings and MFA_ENCRYPTION_KEY where privileged MFA enrollment is required.
3. Run Alembic migrations from onecore-ecosystem in a single controlled release job using the intended production DATABASE_URL: `alembic upgrade head`. Do not run competing migration jobs. CI validates migration upgrade, downgrade and re-upgrade against a disposable PostgreSQL database; this is not a production backup/restore drill.
4. Deploy to staging first. Verify /health, /ready, OpenAPI, tenant and branch authorization, authentication/MFA, backup configuration and application smoke tests.
5. Run provider sandbox/UAT only with authorized credentials and approved specifications. Do not mark M-Pesa, KRA eTIMS, SHA or bank connections live/certified until provider acceptance and reconciliation evidence exist.
6. Obtain release approval, deploy, and retain the exact commit, migration revision, smoke-test evidence and rollback decision.

## Monitoring and backup

The scheduled production monitor requires the repository secret ONECORE_HEALTHCHECK_URL containing the actual deployed API base URL. ONECORE_MONITOR_TOKEN is optional and enables authenticated provider-configuration checks. A scheduled monitor run currently fails before probing because ONECORE_HEALTHCHECK_URL is not configured; no production health result is established.

The encrypted PostgreSQL backup workflow requires ONECORE_BACKUP_DATABASE_URL, ONECORE_BACKUP_S3_BUCKET, ONECORE_BACKUP_AWS_ACCESS_KEY_ID, ONECORE_BACKUP_AWS_SECRET_ACCESS_KEY and ONECORE_BACKUP_AWS_REGION. The manual restore drill additionally requires an isolated empty recovery database and the documented restore secrets. Follow docs/FINANCE_PAYROLL_RECOVERY.md; a source-code CI pass does not prove backup or restore success.

## Incident handling

Create an incident ID, classify SEV-1 to SEV-4, appoint incident commander/technical owner/comms owner, contain impact, protect data, communicate through status channels, restore and verify data, reconcile queues and integrations, then publish root-cause and corrective actions.

## Maintenance

Record scope, affected tenants/modules, window/timezone, reason, risk, owner, approvals, backups, health checks and rollback. Apply only approved restrictions. Preserve local offline POS operation. Run smoke tests and data integrity checks before reopening.

## Recovery

Define RTO/RPO with the business and verify them through isolated restore drills. Include object storage, encryption keys, application configuration, database roles/grants, external integration state and queued offline POS transactions in the recovery plan. Do not assume a database dump alone restores the complete OneCore ecosystem.
