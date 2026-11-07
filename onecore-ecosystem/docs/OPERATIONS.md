# Operations runbook starter

## Deploy
1. Build and scan the container.
2. Supply production settings through a secret manager.
3. Run migrations (add Alembic before production schema evolution).
4. Verify `/health`, database connectivity and provider-disabled state.
5. Deploy to staging, run smoke and integration tests, then obtain release approval.

## Incident handling
Create an incident ID, classify SEV-1 to SEV-4, appoint incident commander/technical owner/comms owner, contain impact, protect data, communicate through status channels, restore and verify data, reconcile queues and integrations, then publish root-cause and corrective actions.

## Maintenance
Record scope, affected tenants/modules, window/timezone, reason, risk, owner, approvals, backups, health checks and rollback. Apply only approved restrictions. Preserve local offline POS operation. Run smoke tests and data integrity checks before reopening.

## Backups
Configure database and object-storage backups, encryption, retention, PITR, integrity checks and restore drills. Define RTO/RPO with the business; do not assume defaults.
