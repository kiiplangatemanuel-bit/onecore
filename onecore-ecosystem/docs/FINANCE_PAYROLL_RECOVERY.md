# Finance, payroll and recovery operations

## Multi-currency accounting

- Configure each organization's base currency before posting any foreign-currency transactions.
- Add a dated exchange rate at `POST /api/v1/accounting/fx/rates`. The rate convention is **foreign currency units per one unit of base currency**; when KES is the base currency and 1 USD = 130 KES, store approximately 0.0076923077 USD per KES. Conversion to base currency divides the foreign amount by this rate.
- Post a foreign-currency transaction at `POST /api/v1/accounting/fx/postings`. The endpoint converts the foreign amount to base currency, writes a balanced base-currency general-ledger journal, and stores the source rate, foreign amount and idempotency key.
- At period end, prepare `POST /api/v1/accounting/fx/revaluations` with the verified foreign-currency monetary positions, carrying values, closing rate, and dedicated FX gain/loss accounts. Asset and liability revaluation directions are handled separately. The resulting journal is balanced and the input position snapshot is retained.
- The supplied balances are an explicit finance-controlled subledger extract. Reconcile them to the AR/AP/bank/loan source ledgers before posting. This API does not infer foreign balances from historic base-currency journals.

## Statutory payroll remittances

- Prepare a statutory batch from approved payroll runs with posted, unreversed accrual journals from one branch and one pay period using `POST /api/v1/payroll/statutory-batches`.
- The batch calculates PAYE, employee/employer NSSF, SHIF, employee/employer Housing Levy and employee pension from immutable payslip snapshots.
- Submit, independently approve, then record the externally confirmed payment reference and actual amount; the amount must exactly reconcile to the batch total before the settlement journal is posted. Preparer/submitter/approver/payment segregation is enforced.
- `GET /api/v1/payroll/statutory-batches/{id}/return` exports a versioned calculation schedule. It is **not** a KRA/NSSF/SHA filing receipt and does not submit money or returns to those providers. Verify current official rates and filing formats, then file through the approved authority channels and retain the acknowledgement.

## PostgreSQL backup and recovery

The script `scripts/postgres_backup.py` uses PostgreSQL custom-format archives and requires `pg_dump` and `pg_restore` from a supported PostgreSQL client installation.

1. Set `ONECORE_BACKUP_DATABASE_URL` (or the existing `SUPABASE_DB_URL`) in the operator's secret environment. Never commit credentials.
2. Run `python scripts/postgres_backup.py backup --output /secure-backups/onecore-YYYYMMDD-HHMM.dump`.
3. Copy the archive and its adjacent `.manifest.json` to encrypted, access-controlled off-host storage. Include object-storage data, configuration and key escrow in the wider recovery plan; a database dump alone is not a complete platform backup.
4. The scheduled GitHub workflow `.github/workflows/onecore-postgres-backup.yml` creates and verifies a daily custom-format dump, then uploads the archive and checksum manifest to a private S3 bucket with SSE-S3 encryption. Configure repository secrets `ONECORE_BACKUP_DATABASE_URL`, `ONECORE_BACKUP_S3_BUCKET`, `ONECORE_BACKUP_AWS_ACCESS_KEY_ID`, `ONECORE_BACKUP_AWS_SECRET_ACCESS_KEY` and `ONECORE_BACKUP_AWS_REGION`. Use a dedicated least-privilege upload identity and configure an S3 lifecycle/retention policy. For Supabase, use a supported direct/session PostgreSQL connection URL suitable for `pg_dump`, not the transaction-mode pooler. Run `python scripts/postgres_backup.py verify --archive /secure-backups/onecore-....dump` after download and periodically restore to a newly provisioned isolated PostgreSQL database.
5. For a restore, set `ONECORE_RESTORE_DATABASE_URL` to a newly created **empty isolated target**, then run `python scripts/postgres_backup.py restore --archive ... --confirm-target <exact-db-name> --allow-restore`. The tool never runs destructive `--clean` restore flags.
6. Provision the expected database runtime/migration roles before restore; the archive preserves ACL grants but does not contain cluster-global role definitions. Validate Alembic head, tenant RLS/FORCE policies, runtime role grants, representative tenant counts, accounting debit/credit totals, payroll batch snapshots, object references and application smoke tests before routing traffic.
7. Record the drill operator, archive checksum, restore target, start/end times, measured RPO/RTO, test results and sign-off. Keep the recovered system isolated until approval.

Supabase-managed PITR, automated snapshots, cross-region replication and retention are configured in the Supabase project and are not created by this application script. Set and test the organization's actual RPO/RTO against the selected Supabase plan. Do not represent this script as enabling PITR or cross-region DR.

## Readiness and monitoring

- `GET /health` is a process liveness check only.
- `GET /ready` checks database connectivity. In production it also rejects a superuser/BYPASSRLS runtime role and checks the forced RLS policies on the protected tenant tables, including the new FX and statutory batch tables.
- The scheduled workflow `.github/workflows/onecore-production-monitor.yml` probes `/health`, `/ready` and the OpenAPI FX/payroll routes every 15 minutes. Configure the repository secret `ONECORE_HEALTHCHECK_URL` to the deployed API base URL and enable GitHub Actions failure notifications for the operators.
- Configure the hosting platform to probe `/ready`, alert on non-2xx responses, and retain request/error logs. Alert on failed backups, checksum mismatches, migration failures, payment/provider callback backlog, unremitted statutory batches and restore-drill expiry.
- A green readiness response is not a backup restore test, provider certification, statutory filing confirmation or production UAT sign-off.

- For realized FX reconciliation, use `POST /api/v1/accounting/fx/settlements` with the foreign amount, carrying value, settlement rate, receivable/payable account, bank account and FX gain/loss accounts. It clears the carrying balance and posts the realized difference to gain or loss. Reconcile the supplied carrying value to the actual open item before posting.
